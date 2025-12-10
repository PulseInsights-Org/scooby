from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.tools import tool
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import ToolMessage, BaseMessage
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
import logging
import asyncio
import json
import os
from app.core.config import get_config
from app.service.transcript_buffer import TranscriptItem
from app.service.Pinecone_Store import VectoreStore
from app.service.screenshare_metadata_store import ScreenshareMetadataStore

logger = logging.getLogger(__name__)

class EventExtraction(BaseModel):
    """Single extracted event from transcript"""
    timestamp: str = Field(description="Time range in format '00:15-00:18'")
    event: str = Field(description="Detailed description of what happened/was discussed")
    person: str = Field(description="Person who performed the action or led the discussion")
    event_type: Literal["issue-related", "MoM-event", "general-event"] = Field(
        default="general-event",
        description=(
            "Type of event: 'issue-related' for technical issues/blockers/logs, "
            "'MoM-event' for events referring to previous meeting context, "
            "or 'general-event' for everything else."
        ),
    )

class MeetingOutput(BaseModel):
    """Structured output containing events and updated summary"""
    events: List[EventExtraction] = Field(description="List of extracted events from this transcript segment")
    summary: str = Field(description="Complete updated meeting summary (MOM style)")
    suggestion: Optional[str] = Field(default=None, description="Optional suggestion generated using issue knowledge base; may be null")
    screen_analysis: Optional[str] = Field(
        default=None,
        description=(
            "Optional short summary of the most important information derived from "
            "screenshare context in this segment (if any)."
        ),
    )

class SummarizationService:
    """
    LangChain-based service for extracting events and generating global summary.
    Returns structured output with both events timeline and updated MOM summary.
    """

    def __init__(self):
        self.config = get_config()
        # ------------------------------------------------------------
        # 1️⃣ Load Pinecone Stores (issues + MoM)
        # ------------------------------------------------------------
        issues_index_name = "global-issues"
        mom_index_name = "meeting-summaries"

        self.issues_pinecone_store: Optional[VectoreStore] = None
        self.mom_pinecone_store: Optional[VectoreStore] = None
        self.screenshare_metadata_store: Optional[ScreenshareMetadataStore] = ScreenshareMetadataStore()

        try:
            self.issues_pinecone_store = VectoreStore(index_name=issues_index_name)
            self.issues_pinecone_store.setup_index()
            logger.info(f"Initialized VectoreStore for issues index: {issues_index_name}")
        except Exception as e:
            logger.error(f"Failed to initialize issues PineconeStore: {e}")

        try:
            self.mom_pinecone_store = VectoreStore(index_name=mom_index_name)
            self.mom_pinecone_store.setup_index()
            logger.info(f"Initialized VectoreStore for MoM index: {mom_index_name}")
        except Exception as e:
            logger.error(f"Failed to initialize MoM PineconeStore: {e}")

        # -------------------------------------------------------------------
        # 2️⃣ Define LangChain tools (issues + MoM + screenshare) using OpenAI tool calling
        # -------------------------------------------------------------------

        @tool
        def search_meeting_knowledge_base(
            query: str,
            event_type: Literal["issue-related", "MoM-event", "general-event"] = "general-event",
        ) -> str:
            """Search the appropriate meeting knowledge base based on event_type.

            - "issue-related": search issues knowledge base for similar issues.
            - "MoM-event": search previous meeting MoM index for related context.
            - "general-event": no search performed, returns informational message.
            """

            logger.info(
                f"[SummarizationService] Tool 'search_meeting_knowledge_base' invoked with "
                f"query: {query} and event_type: {event_type}"
            )

            # Select appropriate index based on event_type
            store = None
            index_kind = None

            if event_type == "issue-related":
                store = self.issues_pinecone_store
                index_kind = "issues"
                if not store:
                    return "Issues knowledge base is not available."
            elif event_type == "MoM-event":
                store = self.mom_pinecone_store
                index_kind = "mom"
                if not store:
                    return "Meeting MoM index is not available."
            else:
                return "No knowledge base search needed for this event type."

            try:
                matches = store.search_similar_issues(query)

                lines = []
                for m in matches:
                    md = m.get("metadata", {}) or {}

                    if index_kind == "issues":
                        text = (
                            md.get("title")
                            or md.get("summary")
                            or md.get("description")
                            or "(issue without title)"
                        )
                    else:  # mom index
                        text = (
                            md.get("summary")
                            or md.get("notes")
                            or md.get("decision")
                            or "(context snippet)"
                        )

                    lines.append(f"- {text}")

                result_text = "\n".join(lines)
                logger.info("[SummarizationService] Tool 'search_meeting_knowledge_base' returning results")
                return result_text
            except Exception as e:
                logger.error(f"Error in search_meeting_knowledge_base tool: {e}")
                if index_kind == "issues":
                    return f"Error while searching issues knowledge base: {e}"
                elif index_kind == "mom":
                    return f"Error while searching MoM meeting index: {e}"
                return f"Error while searching meeting knowledge base: {e}"

        @tool
        def get_screenshare_frames_by_time(
            participant_name: str,
            timestamp_range: str,
        ) -> Dict[str, Any]:
            """Fetch screenshare frames for a participant within a relative time window.

            Args:
                participant_name: Name of the participant (case-insensitive partial match).
                timestamp_range: Relative time range exactly as in the events/timeline,
                    e.g. "00:10-00:30" or "1:02:03-1:02:30".

            Returns a dict with:
                - count: number of frames found
                - frames: list of minimal frame metadata dictionaries, each including:
                    - s3_key
                    - timestamp_relative
                    - participant_name
            """

            logger.info(
                f"[SummarizationService] Tool 'get_screenshare_frames_by_time' invoked with "
                f"participant_name={participant_name}, range={timestamp_range}"
            )

            store = self.screenshare_metadata_store
            if not store:
                return {"count": 0, "frames": []}

            def _parse_ts(value: str) -> float:
                """Parse a relative timestamp string (SS, MM:SS, or H:MM:SS) into seconds."""
                parts = value.strip().split(":")
                parts = [p.strip() for p in parts if p.strip()]
                if not parts:
                    return 0.0
                if len(parts) == 1:
                    # seconds
                    return float(parts[0])
                if len(parts) == 2:
                    # MM:SS
                    m, s = parts
                    return int(m) * 60 + float(s)
                # H:MM:SS (or longer, we only care about the last 3 units)
                h, m, s = parts[-3], parts[-2], parts[-1]
                return int(h) * 3600 + int(m) * 60 + float(s)

            # Expect range in form "start-end", both sides using the same
            # relative timestamp format as in the events file (e.g. "00:10-00:30").
            try:
                range_str = timestamp_range.strip()
                start_str, end_str = [p.strip() for p in range_str.split("-", 1)]
                start_rel = _parse_ts(start_str)
                end_rel = _parse_ts(end_str)
            except Exception as e:
                logger.error(f"Error parsing timestamp range in get_screenshare_frames_by_time: {e}")
                return {"count": 0, "frames": []}

            # Normalize window in case caller swaps start/end
            if end_rel < start_rel:
                start_rel, end_rel = end_rel, start_rel

            records, count = store.query_frames_by_participant_and_window(
                participant_name=participant_name,
                start_relative=start_rel,
                end_relative=end_rel,
            )

            frames: List[Dict[str, Any]] = []
            for r in records:
                s3_key = r.get("s3_key")
                if not s3_key:
                    continue
                frames.append(
                    {
                        "s3_key": s3_key,
                        "timestamp_relative": r.get("timestamp_relative"),
                        "participant_name": r.get("participant_name"),
                    }
                )

            logger.info(
                f"[SummarizationService] get_screenshare_frames_by_time found {len(frames)} frames "
                f"for participant_name={participant_name}, range_seconds=({start_rel}, {end_rel})"
            )

            return {"count": len(frames), "frames": frames}

        self.tools = [search_meeting_knowledge_base, get_screenshare_frames_by_time]
        self.tool_registry = {tool.name: tool for tool in self.tools}

        # ------------------------------------------------------------
        # 3️⃣ Initialize LLM (event extraction + summary + suggestions)
        # ------------------------------------------------------------
        self.llm = ChatOpenAI(
            model=self.config.model_name,
            temperature=self.config.temperature,
            max_tokens=1500,
            openai_api_key=self.config.openai_api_key,
        ).bind_tools(self.tools)

        self.output_parser = JsonOutputParser(pydantic_object=MeetingOutput)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            ("human", "{input}\n\n{format_instructions}")
        ])

        logger.info(f"Initialized SummarizationService with model: {self.config.model_name} and tool-enabled LLM")

    def _get_system_prompt(self) -> str:
        """System prompt for event extraction and summarization"""
        return """You are an expert meeting analyst. Your task is to:

1. **Extract Events**: Identify key events, discussions, decisions, and actions from the transcript segment
   - Each event should be detailed and specific
   - Include what was discussed/decided/proposed
   - Aggregate related statements into coherent events
   - Not just plain conversational text, but actionable/notable items

2. **Use Screenshare Context When Relevant**:
   - When participants talk about what is on the screen, screen sharing, slides, dashboards, code, or UIs,
     you may call the `get_screenshare_frames_by_time` tool.
   - Pass the speaking participant's name and the time range for the event's timestamp.
   - The tool returns metadata for frames (S3 keys and timestamps). You do **not** see the raw images,
     but you should conceptually treat them as additional visual context about what is being shown.
   - When you infer that a visual element is important (e.g. an error log, dashboard graph, PR diff, design
     mock, architecture diagram), explicitly mention that visual context in the event description and summary,
     phrased in natural language (e.g. "On screen, they reviewed the error log showing 500s on /checkout").
   - Additionally, if there is any meaningful screenshare-related insight in this segment, write a concise,
     human-readable summary of those visual insights into the `screen_analysis` field of the JSON output
     (1–3 short paragraphs max). If there is no relevant screenshare context, set `screen_analysis` to null.

3. **Generate Global Summary**: Create/update a complete meeting summary (Minutes of Meeting style)
   - Concise, professional, plain English
   - If previous summary provided, UPDATE it with new information (don't just append)
   - Maintain chronological flow
   - Focus on: key topics, decisions made, action items, next steps
   - Remove redundancy - integrate new info into existing context

4. **Classify Event Type**
   - For each event, set `event_type` to one of:
     - `"issue-related"` for technical issues/blockers/logs, integration failures, debugging/troubleshooting topics
     - `"MoM-event"` for events that clearly refer to previous meeting context (e.g. what was decided last time, follow-ups from earlier meetings)
     - `"general-event"` for everything else

5. **Issue Knowledge Base Suggestions (ONLY if issue-related events exist)**
   - If at least one event has `event_type = "issue-related"`:
      - Conceptually search the issues knowledge base using the issue event description as the query.
      - Use the retrieved similar issues/solutions to generate a concrete, actionable suggestion.
      - Put the final suggestion text in the `suggestion` field of the output.

6. **MoM / Previous Meeting Context Suggestions (ONLY if MoM-events exist)**
   - If at least one event has `event_type = "MoM-event"`:
      - Conceptually search the previous meeting MoM index using the event description as the query.
      - Use the retrieved previous-meeting context to refine the event description and update the global summary accordingly.

Guidelines:
- Events: Be specific about WHO did/said WHAT
- Summary: Professional MOM format, not conversational
- Maintain continuity across the entire meeting
- Preserve important details (dates, numbers, names, commitments)
- Suggestions must be meaningful, practical and tied to the described issues or MoM-related context."""

    def _build_input(
        self,
        transcript_items: List[TranscriptItem],
        previous_summary: Optional[str] = None
    ) -> str:
        """Build input text for processing"""

        transcript_lines = []
        for item in transcript_items:
            start_str = self._format_timestamp(item.start_time)
            end_str = self._format_timestamp(item.end_time)
            transcript_lines.append(f"[{start_str}-{end_str}] {item.speaker}: {item.text}")

        transcript_text = "\n".join(transcript_lines)

        input_parts = []

        if previous_summary and self.config.continuity_enabled:
            input_parts.append(f"## Current Meeting Summary (to be updated):\n{previous_summary}\n")
        else:
            input_parts.append("## Current Meeting Summary:\n[This is the first segment - create initial summary]\n")

        input_parts.append(f"## New Transcript Segment:\n{transcript_text}\n")

        input_parts.append("## Your Tasks:")
        input_parts.append("1. Extract detailed events from the new transcript segment")
        input_parts.append("2. Update the meeting summary by integrating new information")
        input_parts.append("   - If summary exists: merge new info, remove redundancy, maintain flow")
        input_parts.append("   - If first segment: create comprehensive initial summary")

        return "\n".join(input_parts)

    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds to MM:SS or H:MM:SS"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    async def process_segment(
        self,
        transcript_items: List[TranscriptItem],
        previous_summary: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process transcript segment to extract events and update summary

        Args:
            transcript_items: List of transcript items to process
            previous_summary: Current global summary (to be updated)

        Returns:
            Dict with 'events' (list) and 'summary' (str)
        """
        max_retries = 3
        retry_delay = 2.0

        for attempt in range(max_retries):
            try:
                if not transcript_items:
                    logger.warning("No transcript items to process")
                    return {"events": [], "summary": previous_summary or "", "suggestion": None}

                input_text = self._build_input(transcript_items, previous_summary)

                logger.info(f"Processing {len(transcript_items)} transcript items (attempt {attempt + 1})")
                logger.debug(f"Input length: {len(input_text)} chars")

                format_instructions = self.output_parser.get_format_instructions()

                messages = self.prompt.format_messages(
                    input=input_text,
                    format_instructions=format_instructions,
                )

                ai_message = await self._invoke_with_tools(messages)
                raw_output_text = self._coerce_message_content(ai_message)

                # Log the raw output for debugging
                logger.debug(f"[Screenshare Debug] Raw LLM output: {raw_output_text}")
                
                # Parse structured response (events, summary, suggestion, screen_analysis)
                try:
                    result = self.output_parser.parse(raw_output_text)
                    logger.debug(f"[Screenshare Debug] Parsed result: {json.dumps(result, indent=2)}")
                except Exception as e:
                    logger.error(f"[Screenshare Debug] Error parsing LLM output: {e}")
                    raise

                if not isinstance(result, dict):
                    error_msg = f"Expected dict, got {type(result)}"
                    logger.error(f"[Screenshare Debug] {error_msg}")
                    raise ValueError(error_msg)

                if "events" not in result or "summary" not in result:
                    raise ValueError(f"Missing required keys in result: {result.keys()}")

                events = result.get("events", []) or []
                suggestion_parts: List[str] = []

                # -----------------------------
                # Issue-related suggestions
                # -----------------------------
                if self.issues_pinecone_store and events:
                    issue_events = [e for e in events if e.get("event_type") == "issue-related"]
                    if issue_events:
                        try:
                            issue_query = issue_events[0].get("event") or ""
                            if issue_query:
                                matches = self.issues_pinecone_store.search_similar_issues(issue_query)
                                if matches:
                                    lines = []
                                    for m in matches:
                                        md = m.get("metadata", {}) or {}
                                        title = md.get("title") or md.get("summary") or md.get("description") or ""
                                        if title:
                                            lines.append(f"- {title}")
                                    if lines:
                                        suggestion_parts.append(
                                            "Issue-related suggestions based on similar past issues:\n" + "\n".join(lines)
                                        )
                        except Exception as e:
                            logger.error(f"Error querying issues Pinecone index: {e}")

                # -----------------------------
                # MoM / previous meeting context suggestions
                # -----------------------------
                if self.mom_pinecone_store and events:
                    mom_events = [e for e in events if e.get("event_type") == "MoM-event"]
                    if mom_events:
                        try:
                            mom_query = mom_events[0].get("event") or ""
                            if mom_query:
                                matches = self.mom_pinecone_store.search_similar_issues(mom_query)
                                if matches:
                                    lines = []
                                    for m in matches:
                                        md = m.get("metadata", {}) or {}
                                        context = md.get("summary") or md.get("notes") or md.get("decision") or ""
                                        if context:
                                            lines.append(f"- {context}")
                                    if lines:
                                        suggestion_parts.append(
                                            "Previous meeting context and follow-ups:\n" + "\n".join(lines)
                                        )
                        except Exception as e:
                            logger.error(f"Error querying MoM Pinecone index: {e}")

                # suggestion is optional; 
                if suggestion_parts:
                    final_suggestion = "\n\n".join(suggestion_parts)
                    result["suggestion"] = final_suggestion
                    logger.info(f"[SummarizationService] Final suggestion generated: {final_suggestion}")
                elif "suggestion" not in result:
                    result["suggestion"] = None

                # Log screenshare analysis status
                screen_analysis = result.get('screen_analysis')
                if screen_analysis:
                    logger.info(
                        f"Extracted {len(result['events'])} events, "
                        f"summary length: {len(result['summary'])} chars, "
                        f"suggestion present: {result['suggestion'] is not None}, "
                        f"screenshare analysis: {len(screen_analysis)} chars"
                    )
                    logger.debug(f"[Screenshare Debug] Screenshare analysis content: {screen_analysis}")
                else:
                    logger.info(
                        f"Extracted {len(result['events'])} events, "
                        f"summary length: {len(result['summary'])} chars, "
                        f"suggestion present: {result['suggestion'] is not None}, "
                        "no screenshare analysis in this segment"
                    )
                    
                    # Log if there were any tool calls that might be related to screenshares
                    if hasattr(ai_message, 'tool_calls') and ai_message.tool_calls:
                        tool_names = [t.get('name', 'unknown') for t in ai_message.tool_calls]
                        logger.debug(f"[Screenshare Debug] Tool calls in this segment: {tool_names}")
                        if 'get_screenshare_frames_by_time' in tool_names:
                            logger.debug("[Screenshare Debug] Screenshare tool was called but no analysis was returned")

                return result

            except OutputParserException as e:
                raw_output = getattr(e, "llm_output", "") or ""
                logger.error(
                    f"Output parser error (attempt {attempt + 1}/{max_retries}): {e}; "
                    "trying to recover raw LLM output."
                )
                recovered = self._recover_structured_output(raw_output)
                if recovered:
                    logger.info(
                        "[SummarizationService] Successfully recovered structured output "
                        "after parser failure."
                    )
                    return recovered

                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.exception("All attempts failed - Output parser errors")
                    return self._create_fallback_output(transcript_items, previous_summary)

            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.exception("All attempts failed - JSON parsing error")
                    return self._create_fallback_output(transcript_items, previous_summary)

    def _recover_structured_output(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """
        Attempt to salvage structured JSON from an invalid LLM response by
        stripping code fences and isolating the outermost JSON object.
        """
        if not raw_text:
            return None

        text = raw_text.strip()
        if not text:
            return None

        if text.startswith("```"):
            text = text[3:]
            text = text.lstrip()
            if text.lower().startswith("json"):
                text = text[4:].lstrip()
            closing = text.rfind("```")
            if closing != -1:
                text = text[:closing]

        first = text.find("{")
        last = text.rfind("}")
        if first == -1 or last == -1 or last <= first:
            return None

        candidate = text[first : last + 1]
        try:
            parsed_json = json.loads(candidate)
            meeting_output = MeetingOutput(**parsed_json)
            return meeting_output.model_dump()
        except Exception as parse_err:
            logger.error(f"Failed to recover structured output from LLM response: {parse_err}")
            return None

    async def _invoke_with_tools(self, messages: List[BaseMessage]) -> BaseMessage:
        """
        Invoke the LLM with tool calling support.
        
        Args:
            messages: List of messages to send to the LLM
            
        Returns:
            The final message from the LLM after processing any tool calls
        """
        current_messages = messages
        max_iterations = 5  # Prevent infinite loops
        
        for _ in range(max_iterations):
            # Invoke the LLM with the current messages
            response = await self.llm.ainvoke(current_messages)
            
        # If there are no tool calls, we're done
        if not hasattr(response, 'tool_calls') or not response.tool_calls:
            return response
            
        # Process tool calls
        tool_messages = []
        for tool_call in response.tool_calls:
            tool_name = tool_call['name']
            tool_args = tool_call.get('args', {})
                    
            # Log the original tool call
            logger.debug(f"Processing tool call: {tool_name} with args: {tool_args}")
                    
            # Handle parameter name mismatches for each tool
            processed_args = {}
            if tool_name == 'get_screenshare_frames_by_time':
                # Tool schema expects: participant_name, timestamp_range
                # Accept aliases from the LLM and map them into the correct names.
                if 'participant_name' in tool_args:
                    processed_args['participant_name'] = tool_args['participant_name']
                elif 'participant_id' in tool_args:
                    # Some prompts may encourage the LLM to send participant_id
                    processed_args['participant_name'] = tool_args['participant_id']

                if 'timestamp_range' in tool_args:
                    processed_args['timestamp_range'] = tool_args['timestamp_range']
                elif 'time_range' in tool_args:
                    # Our earlier attempt renamed this incorrectly; keep the
                    # key as timestamp_range to satisfy the tool's schema.
                    processed_args['timestamp_range'] = tool_args['time_range']

                # Pass through any extra keys just in case, but do not rename
                # away from the required schema fields.
                for k, v in tool_args.items():
                    if k not in processed_args:
                        processed_args[k] = v

            elif tool_name == 'search_meeting_knowledge_base':
                # Tool schema expects: query, event_type
                # Map various query key variants back to query.
                if 'query' in tool_args:
                    processed_args['query'] = tool_args['query']
                elif 'query_text' in tool_args:
                    processed_args['query'] = tool_args['query_text']
                elif 'queryText' in tool_args:
                    processed_args['query'] = tool_args['queryText']

                # event_type is optional but supported; keep the same name.
                if 'event_type' in tool_args:
                    processed_args['event_type'] = tool_args['event_type']
                elif 'eventType' in tool_args:
                    processed_args['event_type'] = tool_args['eventType']

                # Include any additional keys without renaming required ones.
                for k, v in tool_args.items():
                    if k not in processed_args:
                        processed_args[k] = v
            else:
                # For other tools, pass through all arguments as-is
                processed_args = tool_args
                    
            if tool_name not in self.tool_registry:
                error_msg = f"Unknown tool: {tool_name}"
                logger.error(error_msg)
                tool_messages.append(ToolMessage(
                    content=error_msg,
                    tool_call_id=tool_call['id']
                ))
                continue
                        
            try:
                tool_func = self.tool_registry[tool_name]
                logger.debug(f"Calling tool {tool_name} with processed args: {processed_args}")
                        
                # Use invoke() instead of direct call to handle both sync and async tools
                if asyncio.iscoroutinefunction(tool_func.invoke if hasattr(tool_func, 'invoke') else tool_func):
                    if hasattr(tool_func, 'invoke'):
                        tool_result = await tool_func.invoke(processed_args)
                    else:
                        tool_result = await tool_func(**processed_args)
                else:
                    if hasattr(tool_func, 'invoke'):
                        tool_result = tool_func.invoke(processed_args)
                    else:
                        tool_result = tool_func(**processed_args)
                        
                if not isinstance(tool_result, str):
                    tool_result = str(tool_result)
                        
                tool_messages.append(ToolMessage(
                    content=tool_result,
                    tool_call_id=tool_call['id']
                ))
            except Exception as e:
                logger.error(f"Error calling tool {tool_name}: {e}")
                tool_messages.append(ToolMessage(
                    content=f"Error calling tool {tool_name}: {str(e)}",
                    tool_call_id=tool_call['id']
                ))
            
            # Add the tool responses to the message history
            current_messages = current_messages + [response] + tool_messages
        
        # If we get here, we've reached max iterations
        logger.warning(f"Reached max iterations ({max_iterations}) in tool calling loop")
        return current_messages[-1]  # Return the last message

    def _coerce_message_content(self, message: Any) -> str:
        """
        Extract content from a message object, handling different message types.
        
        Args:
            message: The message object from the LLM
            
        Returns:
            The message content as a string
        """
        if hasattr(message, 'content') and message.content:
            if isinstance(message.content, str):
                return message.content
            if hasattr(message.content, 'as_string'):
                return message.content.as_string()
            return str(message.content)
        elif hasattr(message, 'text'):
            return message.text
        elif hasattr(message, 'response'):
            return self._coerce_message_content(message.response)
        return str(message)

    def _create_fallback_output(
        self,
        transcript_items: List[TranscriptItem],
        previous_summary: Optional[str]
    ) -> Dict[str, Any]:
        """Create fallback output when LLM fails"""
        speakers = {item.speaker for item in transcript_items}

        events = []
        for item in transcript_items:
            start_str = self._format_timestamp(item.start_time)
            end_str = self._format_timestamp(item.end_time)
            events.append({
                "timestamp": f"{start_str}-{end_str}",
                "event": item.text[:100] + "..." if len(item.text) > 100 else item.text,
                "person": item.speaker
            })

        # If we already have a previous summary, keep it as-is to avoid
        # repeatedly appending noisy auto-generated markers.
        if previous_summary:
            updated_summary = previous_summary.strip()
        else:
            # Only add a single lightweight auto-generated note when there
            # was no prior summary at all.
            fallback_addition = (
                f"[Auto-generated] Summary placeholder for a segment with "
                f"{len(transcript_items)} items from speakers: {', '.join(speakers)}"
            )
            updated_summary = fallback_addition

        return {
            "events": events,
            "summary": updated_summary.strip(),
            "suggestion": None,
        }
