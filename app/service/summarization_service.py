from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import logging
import asyncio
import json
import os
from app.core.config import get_config
from app.service.transcript_buffer import TranscriptItem
from app.service.Pinecone_Store import PineconeStore

logger = logging.getLogger(__name__)


class EventExtraction(BaseModel):
    """Single extracted event from transcript"""
    timestamp: str = Field(description="Time range in format '00:15-00:18'")
    event: str = Field(description="Detailed description of what happened/was discussed")
    person: str = Field(description="Person who performed the action or led the discussion")
    is_issue: Optional[bool] = Field(
        default=None,
        description="True if this event contains an issue/error/blocker/logs; otherwise False or null",
    )


class MeetingOutput(BaseModel):
    """Structured output containing events and updated summary"""
    events: List[EventExtraction] = Field(description="List of extracted events from this transcript segment")
    summary: str = Field(description="Complete updated meeting summary (MOM style)")
    suggestion: Optional[str] = Field(default=None, description="Optional suggestion generated using issue knowledge base; may be null")


class SummarizationService:
    """
    LangChain-based service for extracting events and generating global summary.
    Returns structured output with both events timeline and updated MOM summary.
    """

    def __init__(self):
        self.config = get_config()
        # ------------------------------------------------------------
        # 1️⃣ Load Pinecone Store 
        # ------------------------------------------------------------
        index_name = "global-issues"  
        self.pinecone_store: Optional[PineconeStore] = None
        try:
            self.pinecone_store = PineconeStore(index_name=index_name)
            logger.info(f"Initialized PineconeStore for issues index: {index_name}")
        except Exception as e:
            logger.error(f"Failed to initialize PineconeStore: {e}")

        # ------------------------------------------------------------
        # 2️⃣ Define OpenAI Tool schema 
        # ------------------------------------------------------------
        self.search_tool_def = {
            "type": "function",
            "function": {
                "name": "search_in_issues_index",
                "description": "Search similar issues in Pinecone index for troubleshooting and suggestions",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"],
                },
            },
        }

        # ------------------------------------------------------------
        # 3️⃣ Initialize LLM (event extraction + summary + suggestion)
        # ------------------------------------------------------------
        self.llm = ChatOpenAI(
            model=self.config.model_name,
            temperature=self.config.temperature,
            max_tokens=1500,
            openai_api_key=self.config.openai_api_key,
            tools=[self.search_tool_def],
            tool_choice="auto",
        )

        self.output_parser = JsonOutputParser(pydantic_object=MeetingOutput)

        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self._get_system_prompt()),
            ("human", "{input}\n\n{format_instructions}")
        ])

        self.chain = self.prompt | self.llm | self.output_parser

        logger.info(f"Initialized SummarizationService with model: {self.config.model_name} and tool-enabled LLM")

    def _get_system_prompt(self) -> str:
        """System prompt for event extraction and summarization"""
        return """You are an expert meeting analyst. Your task is to:

1. **Extract Events**: Identify key events, discussions, decisions, and actions from the transcript segment
   - Each event should be detailed and specific
   - Include what was discussed/decided/proposed
   - Aggregate related statements into coherent events
   - Not just plain conversational text, but actionable/notable items

2. **Generate Global Summary**: Create/update a complete meeting summary (Minutes of Meeting style)
   - Concise, professional, plain English
   - If previous summary provided, UPDATE it with new information (don't just append)
   - Maintain chronological flow
   - Focus on: key topics, decisions made, action items, next steps
   - Remove redundancy - integrate new info into existing context

3. **Classify Issue Events**
   - For each event, set `is_issue = true` ONLY IF it clearly contains:
     - errors, issues, warnings, logs
     - blockers or being blocked
     - integration failures or API issues
     - debugging / troubleshooting topics
   - Otherwise, set `is_issue = false` or leave it null.

4. **Suggestion Generation (ONLY if issue events exist)**
   - If at least one event has `is_issue = true`:
       - Conceptually call the tool `search_in_issues_index` using the issue event description as the query.
       - Use those retrieved similar issues/solutions to generate a concrete, actionable suggestion.
       - Put the final suggestion text in the `suggestion` field of the output.
   - If there are no issue events, set `suggestion = null`.

Guidelines:
- Events: Be specific about WHO did/said WHAT
- Summary: Professional MOM format, not conversational
- Maintain continuity across the entire meeting
- Preserve important details (dates, numbers, names, commitments)
- Suggestions must be meaningful, practical and tied to the described issues."""

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

                # Invoke chain (LLM handles events, summary, and suggestion in one pass)
                result = await self.chain.ainvoke({
                    "input": input_text,
                    "format_instructions": format_instructions,
                })

                if not isinstance(result, dict):
                    raise ValueError(f"Expected dict, got {type(result)}")

                if "events" not in result or "summary" not in result:
                    raise ValueError(f"Missing required keys in result: {result.keys()}")

                # suggestion is optional; if model does not return it, default to None
                if "suggestion" not in result:
                    result["suggestion"] = None

                logger.info(
                    f"Extracted {len(result['events'])} events, "
                    f"summary length: {len(result['summary'])} chars, "
                    f"suggestion present: {result['suggestion'] is not None}"
                )

                return result

            except json.JSONDecodeError as e:
                logger.error(f"JSON parsing error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.exception("All attempts failed - JSON parsing error")
                    return self._create_fallback_output(transcript_items, previous_summary)

            except Exception as e:
                logger.error(f"Processing attempt {attempt + 1}/{max_retries} failed: {e}")

                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.exception("All processing attempts failed")
                    return self._create_fallback_output(transcript_items, previous_summary)

        return self._create_fallback_output(transcript_items, previous_summary)

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

        fallback_addition = f"\n\n[Auto-generated] Segment with {len(transcript_items)} items from speakers: {', '.join(speakers)}"
        updated_summary = (previous_summary or "") + fallback_addition

        return {
            "events": events,
            "summary": updated_summary.strip(),
            "suggestion": None,
        }
