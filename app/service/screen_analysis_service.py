import logging
from typing import Optional, Tuple, List, Dict, Any

import google.generativeai as genai

from app.core.config import get_config
from app.service.screenshare_buffer import ScreenshareRedisBuffer
from app.service.summary_storage import SummaryStorage


logger = logging.getLogger(__name__)


class ScreenAnalysisService:
    """Vision-based analysis over recent screenshare frames.

    This service:
      1) Reads the events timeline file for a meeting.
      2) Finds the most recent event that appears to be screenshare-related.
      3) Uses that event text and participant name as context to select frames
         from Redis for the same bot + participant.
      4) Calls a vision model (Gemini) with those frames + event text to
         produce a helper-focused analysis string.
    """

    def __init__(self) -> None:
        self.config = get_config()
        self.buffer = ScreenshareRedisBuffer()
        
        # Initialize placeholders for new indexes (mocked for now)
        from app.service.Pinecone_Store import VectoreStore
        self.company_store = VectoreStore(index_name="company_data")
        self.product_store = VectoreStore(index_name="products")

    async def _format_customer_summary(self, storage) -> str:
        """Fetch and format customer summary from cached storage."""
        if not storage:
            logger.warning("[ScreenAnalysisService] No storage available for customer summary")
            return "Customer summary data not available."

        summary_data = await storage.get_analytics_summary()
        if not summary_data:
            logger.warning("[ScreenAnalysisService] Customer summary not found in storage")
            return "Customer summary data not available. Please ensure analytics data was fetched when bot was added."

        # Format the summary data for the prompt
        try:
            formatted = []
            formatted.append(f"**Customer**: {summary_data.get('name', 'Unknown')}")
            formatted.append(f"**Health Score**: {summary_data.get('health_score', 'N/A')}/100")
            formatted.append(f"**Sentiment**: {summary_data.get('sentiment', 'N/A').capitalize()}")

            if summary_data.get('customer_intent'):
                formatted.append(f"\n**Customer Intent**: {summary_data['customer_intent']}")

            if summary_data.get('summary'):
                formatted.append(f"\n**Summary**: {summary_data['summary']}")

            if summary_data.get('risks'):
                formatted.append(f"\n**Risks**: {summary_data['risks']}")

            if summary_data.get('opportunities'):
                formatted.append(f"\n**Opportunities**: {summary_data['opportunities']}")

            if summary_data.get('key_topics'):
                formatted.append(f"\n**Key Topics**: {summary_data['key_topics']}")

            return "\n".join(formatted)

        except Exception as e:
            logger.exception(f"[ScreenAnalysisService] Error formatting customer summary: {e}")
            return "Error formatting customer summary data."

    async def _format_recent_interactions(self, storage) -> str:
        """Fetch and format recent interactions from cached storage."""
        if not storage:
            logger.warning("[ScreenAnalysisService] No storage available for recent interactions")
            return "Recent interactions data not available."

        interactions_data = await storage.get_analytics_interactions()
        if not interactions_data:
            logger.warning("[ScreenAnalysisService] Recent interactions not found in storage")
            return "Recent interactions data not available. Please ensure analytics data was fetched when bot was added."

        # Format the interactions data for the prompt
        try:
            formatted = []
            total_count = interactions_data.get('total_count', 0)
            formatted.append(f"**Total Recent Interactions**: {total_count}")

            by_source = interactions_data.get('by_source', {})
            for source, interactions in by_source.items():
                if interactions:
                    formatted.append(f"\n**{source.upper()} ({len(interactions)} interactions)**:")
                    for interaction in interactions[:5]:  # Show top 5 per source
                        timestamp = interaction.get('timestamp', 'N/A')
                        summary = interaction.get('summary', 'No summary')
                        sentiment = interaction.get('sentiment', 'neutral')
                        if summary:
                            formatted.append(f"  - [{timestamp}] {summary} (Sentiment: {sentiment})")

            return "\n".join(formatted) if formatted else "No recent interactions found."

        except Exception as e:
            logger.exception(f"[ScreenAnalysisService] Error formatting recent interactions: {e}")
            return "Error formatting recent interactions data."

    def _parse_event_line(self, line: str) -> Optional[Tuple[str, str, str]]:
        """Parse a single event line from the events.txt file.

        Expected format (from SummaryStorage.append_events):
            [timestamp] [event_desc] [by person]
        """
        text = line.strip()
        if not text or not text.startswith("["):
            return None

        try:
            # Split on `] [` boundaries
            parts = text.split("] [")
            if len(parts) < 3:
                return None

            # [00:12-00:13
            ts_raw = parts[0].lstrip("[").strip()

            # event description, may still start with `[` or end with `]`
            event_raw = parts[1].strip()
            if event_raw.startswith("["):
                event_raw = event_raw[1:]
            if event_raw.endswith("]"):
                event_raw = event_raw[:-1]
            event_desc = event_raw.strip()

            # by person]
            person_raw = parts[2].strip()
            if person_raw.endswith("]"):
                person_raw = person_raw[:-1]
            if person_raw.lower().startswith("by "):
                person_raw = person_raw[3:]
            person = person_raw.strip()

            if not ts_raw or not event_desc or not person:
                return None

            return ts_raw, event_desc, person
        except Exception:
            return None

    # Legacy latest-screenshare helpers removed in favor of timestamp-based analysis

    def _timestamp_to_seconds(self, ts: str) -> Optional[float]:
        """Convert a timestamp string like 'MM:SS' or 'H:MM:SS' to seconds."""
        try:
            parts = ts.split(":")
            parts = [int(p) for p in parts]
            if len(parts) == 2:
                m, s = parts
                return m * 60 + s
            if len(parts) == 3:
                h, m, s = parts
                return h * 3600 + m * 60 + s
        except Exception:
            return None
        return None

    def _range_to_seconds(self, range_str: str) -> Optional[Tuple[float, float]]:
        """Convert a 'start-end' timestamp range (e.g. '07:41-07:59') to (start, end) seconds."""
        try:
            start_str, end_str = range_str.split("-", 1)
            start = self._timestamp_to_seconds(start_str.strip())
            end = self._timestamp_to_seconds(end_str.strip())
            if start is None or end is None:
                return None
            return start, end
        except Exception:
            return None

    async def analyze_around_time(
        self,
        *,
        bot_id: str,
        storage: SummaryStorage,
        reference_timestamp: float,
        window_seconds: float = 5.0,
    ) -> Optional[str]:
        """Run vision-based analysis for events/transcripts around a given time.

        Uses a [T - window_seconds, T] window in meeting-relative seconds. First
        tries to use events in that window; if none are found, falls back to
        transcript lines. Then selects recent frames for the same participant
        near that time and calls the vision model.
        """

        if not bot_id or not storage or reference_timestamp is None:
            return None

        events_path = storage.get_events_path()
        transcript_path = storage.get_transcript_path()

        window_start = max(0.0, reference_timestamp - window_seconds)
        window_end = reference_timestamp

        logger.info(
            "[ScreenAnalysisService] Time-windowed analysis window: %.2fs to %.2fs (ref=%.2fs, window=%.2fs)",
            window_start,
            window_end,
            reference_timestamp,
            window_seconds,
        )

        context_lines: List[str] = []
        participant_name: Optional[str] = None

        # 1) Try events in the window
        try:
            with open(events_path, "r", encoding="utf-8") as f:
                for line in f:
                    parsed = self._parse_event_line(line)
                    if not parsed:
                        continue
                    ts_raw, event_desc, person = parsed
                    rng = self._range_to_seconds(ts_raw)
                    if not rng:
                        continue
                    start_sec, end_sec = rng
                    if end_sec >= window_start and start_sec <= window_end:
                        logger.info(
                            "[ScreenAnalysisService] Selected EVENT [%s] (%.2f-%.2f)s for window [%.2f-%.2f]s (person=%s)",
                            ts_raw,
                            start_sec,
                            end_sec,
                            window_start,
                            window_end,
                            person,
                        )
                        context_lines.append(f"- {event_desc}")
                        participant_name = person  # last matching person wins
        except FileNotFoundError:
            logger.debug("[ScreenAnalysisService] Events file not found for time-windowed analysis: %s", events_path)
        except Exception:
            logger.exception(
                "[ScreenAnalysisService] Error while scanning events file for time-windowed analysis: %s",
                events_path,
            )

        # 2) If no events, fallback to transcript lines in the window
        if not context_lines:
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    for line in f:
                        text = line.strip()
                        if not text or not text.startswith("["):
                            continue
                        try:
                            ts_part, rest = text.split("]", 1)
                            ts_range = ts_part.lstrip("[").strip()
                            rng = self._range_to_seconds(ts_range)
                            if not rng:
                                continue
                            start_sec, end_sec = rng
                            if end_sec >= window_start and start_sec <= window_end:
                                logger.info(
                                    "[ScreenAnalysisService] Selected TRANSCRIPT [%s] (%.2f-%.2f)s for window [%.2f-%.2f]s",
                                    ts_range,
                                    start_sec,
                                    end_sec,
                                    window_start,
                                    window_end,
                                )
                                context_lines.append(rest.strip())
                                if participant_name is None and ":" in rest:
                                    speaker, _ = rest.split(":", 1)
                                    participant_name = speaker.strip()
                        except Exception:
                            continue
            except FileNotFoundError:
                logger.debug(
                    "[ScreenAnalysisService] Transcript file not found for time-windowed analysis: %s",
                    transcript_path,
                )
            except Exception:
                logger.exception(
                    "[ScreenAnalysisService] Error while scanning transcript file for time-windowed analysis: %s",
                    transcript_path,
                )

        if not context_lines:
            return (
                "No recent events or transcripts were found in the last few seconds of "
                "the meeting. Try speaking about the issue and sharing your screen, then "
                "run /capture again."
            )

        if not participant_name:
            participant_name = "Unknown participant"

        logger.info(
            "[ScreenAnalysisService] Using time-windowed context from %.2fs to %.2fs for participant '%s'",
            window_start,
            window_end,
            participant_name,
        )

        # 3) Fetch frames for this bot + participant within the same time window
        # used for events/transcripts. We pull more than needed from Redis and
        # then filter down to frames whose timestamp_relative lies inside
        # [window_start, window_end], sending up to vision_max_images_per_request
        # frames to the vision model.

        max_frames = self.config.vision_max_images_per_request
        if max_frames <= 0:
            max_frames = 5

        recent_frames: List[Dict[str, Any]] = self.buffer.get_recent_frames_for_bot(
            bot_id=bot_id,
            max_frames=max_frames * 5,
        )

        candidate_frames: List[Dict[str, Any]] = []
        for frame in recent_frames:
            pn = (frame.get("participant_name") or "").lower()
            if participant_name.lower() not in pn:
                continue

            ts_rel = frame.get("timestamp_relative")
            if ts_rel is None:
                continue

            if window_start <= ts_rel <= window_end:
                candidate_frames.append(frame)

        if candidate_frames:
            ts_vals = [f.get("timestamp_relative") or 0.0 for f in candidate_frames]
            logger.info(
                "[ScreenAnalysisService] Frames window for bot_id=%s participant=%s: window=[%.2f-%.2f]s, candidates=%d, ts_min=%.2f, ts_max=%.2f",
                bot_id,
                participant_name,
                window_start,
                window_end,
                len(candidate_frames),
                min(ts_vals),
                max(ts_vals),
            )

        candidate_frames.sort(key=lambda f: f.get("timestamp_relative") or 0.0)
        frames: List[Dict[str, Any]] = candidate_frames[:max_frames]

        if not frames:
            logger.info(
                "[ScreenAnalysisService] No recent frames found around %.2fs for bot_id=%s, participant=%s",
                reference_timestamp,
                bot_id,
                participant_name,
            )
            return (
                "No recent screenshare frames were found around the time you triggered /capture. "
                "Make sure you're actively sharing your screen while describing the issue, then try again."
            )

        if not self.config.vision_enabled or not self.config.gemini_api_key:
            logger.error("[ScreenAnalysisService] Vision disabled or GEMINI_API_KEY missing")
            return (
                "Vision-based analysis is not enabled or GEMINI_API_KEY is missing on "
                "the server. Please contact the system administrator."
            )

        genai.configure(api_key=self.config.gemini_api_key)
        
        tools = [
            {
                "function_declarations": [
                    {
                        "name": "search_knowledge_base",
                        "description": (
                            "Search the company or product knowledge base for information. "
                            "Use 'company_data' for policies, terms, and general company info. "
                            "Use 'products' for product features, specs, and troubleshooting."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Natural language query to search for.",
                                },
                                "index_name": {
                                    "type": "string",
                                    "enum": ["company_data", "products"],
                                    "description": "Which knowledge base to search.",
                                },
                                "top_k": {
                                    "type": "integer",
                                    "description": "Maximum number of results to retrieve.",
                                },
                            },
                            "required": ["query", "index_name"],
                        },
                    }
                ]
            }
        ]
        
        model = genai.GenerativeModel(self.config.vision_model, tools=tools)

        base_prompt = """
You are a sales team helper AI assistant. You are given:
- A few PNG frames from the customer's shared screen
- A short window of what happened in the meeting recently (time window text)
- Customer intent: Global analysis of the customer from onboarding - what they were looking for, are looking for, and might look for
- Recent interactions: Context from multiple sources (Slack, Gmail, Zendesk, Salesforce, etc.)

Your job is to provide strategic sales guidance to help the sales person in this meeting. You should:

1) **Understand the current situation**: Analyze what's happening on screen and in the conversation based on all available context
2) **Provide actionable guidance**: Tell the sales person how to respond, what to say, or what action to take next
3) **Use knowledge base strategically**: If the customer has a question or faces an issue, use the knowledge base tool to find accurate answers about products, features, pricing, or policies

Guidelines for your guidance:
- **Be strategic**: Consider the customer's intent and recent interactions when suggesting what to say
- **Be helpful**: If the customer is stuck on an issue, help resolve it quickly using the knowledge base, then guide the sales person to pivot back to the sales conversation
- **Be contextual**: Reference specific details from recent interactions when relevant (e.g., "They mentioned pricing concerns in Slack yesterday - now is a good time to address ROI")
- **Be concise**: Keep guidance to 2-4 bullet points or a few sentences
- **Focus on guidance, not description**: Don't just describe what you see - tell the sales person what to DO

Examples of good guidance:
- "Customer is stuck on login. Use knowledge base to find the solution, help them resolve it, then pivot to discussing the integration features they asked about in their last email."
- "They're looking at the pricing page. Based on their Salesforce stage (Negotiation) and recent questions about ROI, now is the perfect time to emphasize the enterprise tier value proposition."
- "Customer intent shows they're evaluating competitors. Highlight our unique differentiation points around [specific feature visible on screen]."
""".strip()

        # Fetch and format analytics context from storage
        customer_summary = await self._format_customer_summary(storage)
        recent_interactions = await self._format_recent_interactions(storage)

        window_text = "\n".join(context_lines)
        full_prompt = f"""{base_prompt}

Time window: from {window_start:.1f}s to {window_end:.1f}s (meeting-relative)

CONTEXT:
1. Customer Summary (Health, Sentiment, Intent, Risks, Opportunities):
{customer_summary}

2. Recent Interactions (from Slack, Gmail, Zendesk, Salesforce, etc.):
{recent_interactions}

3. What happened in the meeting recently (Time Window):
Speaker: {participant_name}
{window_text}

You may call the `search_knowledge_base` tool if you need to look up:
- Company policies, terms, pricing ("company_data")
- Product features, specs, troubleshooting ("products")

Based on the customer's screen, the meeting context, their health/sentiment/intent, and recent interactions, provide strategic guidance for the sales person on:
- What to say or do next to move the deal forward
- How to address what's happening right now based on customer's health score and sentiment
- How to leverage this moment considering their risks and opportunities
""".strip()

        image_parts: List[Dict[str, Any]] = []
        for frame in frames[:max_frames]:
            b64 = frame.get("image_base64")
            if not b64:
                continue
            try:
                image_parts.append({
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": b64,
                    }
                })
            except Exception:
                continue

        if not image_parts:
            logger.error("[ScreenAnalysisService] Failed to build image parts from frames for time-windowed analysis")
            return (
                "Screenshare frames were found but could not be decoded for vision "
                "analysis. Please try again or check server logs for details."
            )

        # Helper to execute the search_knowledge_base tool when invoked by Gemini.
        async def _handle_tool_call(tool_name: str, args: dict) -> str:
            if tool_name != "search_knowledge_base":
                return f"Unknown tool: {tool_name}"

            index_name = args.get("index_name")
            query = args.get("query")
            top_k = int(args.get("top_k") or 5)

            if not query:
                return "Query is required."

            store = None
            if index_name == "company_data":
                store = self.company_store
            elif index_name == "products":
                store = self.product_store
            else:
                return f"Invalid index_name: {index_name}. Must be 'company_data' or 'products'."

            try:
                # Mocking the actual search call for now
                return f"[Mock Result from {index_name}] Search for '{query}' returned no results or mocked data."
            except Exception as e:
                logger.error(f"[ScreenAnalysisService] Error querying Pinecone index {index_name}: {e}")
                return f"Error while searching {index_name}: {e}"

        try:
            response = await model.generate_content_async([
                {"text": full_prompt},
                *image_parts,
            ])
            
            # Check for tool calls in the response
            if hasattr(response, "candidates") and response.candidates:
                parts = response.candidates[0].content.parts
                tool_results = []
                for part in parts:
                    func_call = getattr(part, "function_call", None)
                    if not func_call:
                        continue
                    tool_name = getattr(func_call, "name", None)
                    raw_args = getattr(func_call, "args", {}) or {}
                    
                    if not isinstance(raw_args, dict):
                        try:
                            import json as _json
                            raw_args = _json.loads(str(raw_args))
                        except Exception:
                            raw_args = {}
                    
                    tool_output = await _handle_tool_call(tool_name, raw_args)
                    tool_results.append(
                        {
                            "text": f"Tool {tool_name} result:\n{tool_output}",
                        }
                    )

                if tool_results:
                    # Ask the model again with tool outputs and images
                    response = await model.generate_content_async([
                        {"text": full_prompt},
                        # Note: We must re-include images in follow-up turns for Gemini 1.5 usually,
                        # but typically chat history handles it. Since we are doing single-turn-ish, 
                        # we append tool results. 
                        # Ideally we pass history but here we just append text for simplicity as per SuggestionService pattern
                        *image_parts, 
                        *tool_results
                    ])

            analysis_text = (response.text or "").strip()
        except Exception:
            logger.exception("[ScreenAnalysisService] Error calling Gemini vision model for time-windowed analysis")
            return (
                "Failed to analyze screenshare frames via the vision model. "
                "Please try again or check server logs for details."
            )

        if not analysis_text:
            analysis_text = (
                "Vision model returned no analysis text. This may indicate an "
                "internal error or unsupported image format."
            )

        return analysis_text
