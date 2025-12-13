import logging
from typing import Optional, Tuple, List

import google.generativeai as genai

from app.core.config import get_config
from app.service.summary_storage import SummaryStorage
from app.service.summarization_service import SummarizationService


logger = logging.getLogger(__name__)


class SuggestionService:
    """Time-windowed, RAG-backed suggestion generator for live meetings.

    This service:
      1) Reads events and transcript files from SummaryStorage.
      2) Extracts the slice of discussion within a [T - window, T] window.
      3) Optionally queries the issues Pinecone index exposed by
         SummarizationService for similar past issues.
      4) Calls a Gemini text model with this context to produce a short,
         actionable suggestion.
    """

    def __init__(self) -> None:
        self.config = get_config()
        # Reuse the existing SummarizationService instance for access to the
        # issues Pinecone store, rather than creating a new index client.
        self.summarization_service = SummarizationService()
        
        # Initialize placeholders for new indexes (mocked for now)
        # In a real scenario, these would be separate VectoreStore instances
        from app.service.Pinecone_Store import VectoreStore
        self.company_store = VectoreStore(index_name="company_data")
        self.product_store = VectoreStore(index_name="products")

    async def _format_customer_summary(self, storage) -> str:
        """Fetch and format customer summary from cached storage."""
        if not storage:
            logger.warning("[SuggestionService] No storage available for customer summary")
            return "Customer summary data not available."

        summary_data = await storage.get_analytics_summary()
        if not summary_data:
            logger.warning("[SuggestionService] Customer summary not found in storage")
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
            logger.exception(f"[SuggestionService] Error formatting customer summary: {e}")
            return "Error formatting customer summary data."

    async def _format_recent_interactions(self, storage) -> str:
        """Fetch and format recent interactions from cached storage."""
        if not storage:
            logger.warning("[SuggestionService] No storage available for recent interactions")
            return "Recent interactions data not available."

        interactions_data = await storage.get_analytics_interactions()
        if not interactions_data:
            logger.warning("[SuggestionService] Recent interactions not found in storage")
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
            logger.exception(f"[SuggestionService] Error formatting recent interactions: {e}")
            return "Error formatting recent interactions data."

    def _ts_to_seconds(self, ts: str) -> Optional[float]:
        """Convert 'MM:SS' or 'H:MM:SS' timestamp string to seconds."""
        try:
            parts = [int(p) for p in ts.split(":")]
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
        """Convert 'start-end' range like '07:41-07:59' to (start, end) seconds."""
        try:
            start_str, end_str = range_str.split("-", 1)
            start = self._ts_to_seconds(start_str.strip())
            end = self._ts_to_seconds(end_str.strip())
            if start is None or end is None:
                return None
            return start, end
        except Exception:
            return None

    async def generate_suggestion_around_time(
        self,
        *,
        storage: SummaryStorage,
        reference_timestamp: float,
        window_seconds: float = 15.0,
    ) -> Optional[str]:
        """Generate a short, actionable suggestion around a given meeting time.

        Does NOT use the stored suggestion from the summarization pipeline.
        Instead, it:
          - Reads events and transcripts from SummaryStorage.
          - Extracts context from [T - window_seconds, T].
          - Optionally queries the issues Pinecone index for similar issues.
          - Calls a Gemini text model to produce a crisp suggestion.
        """

        if not storage or reference_timestamp is None:
            return None

        events_path = storage.get_events_path()
        transcript_path = storage.get_transcript_path()

        window_start = max(0.0, reference_timestamp - window_seconds)
        window_end = reference_timestamp

        context_lines: List[str] = []

        # 1) Collect events in the time window
        try:
            with open(events_path, "r", encoding="utf-8") as f:
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
                            context_lines.append(f"[EVENT]{rest.strip()}")
                    except Exception:
                        continue
        except FileNotFoundError:
            logger.debug("[SuggestionService] Events file not found: %s", events_path)
        except Exception:
            logger.exception("[SuggestionService] Error while scanning events file: %s", events_path)

        # 2) Collect transcript lines in the time window
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
                            context_lines.append(f"[TRANSCRIPT]{rest.strip()}")
                    except Exception:
                        continue
        except FileNotFoundError:
            logger.debug("[SuggestionService] Transcript file not found: %s", transcript_path)
        except Exception:
            logger.exception("[SuggestionService] Error while scanning transcript file: %s", transcript_path)

        if not context_lines:
            return (
                "No recent discussion was found in the last few seconds of the meeting. "
                "Try describing the issue out loud, then run /suggest again."
            )

        joined_context = "\n".join(context_lines)

        if not self.config.gemini_api_key:
            logger.error("[SuggestionService] GEMINI_API_KEY missing; cannot generate suggestion")
            return (
                "Suggestion model is not configured on the server (missing GEMINI_API_KEY). "
                "Please contact the system administrator."
            )

        genai.configure(api_key=self.config.gemini_api_key)
        # Expose Pinecone-backed issues search as a Gemini tool so the model can
        # decide when to call it.
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

        model = genai.GenerativeModel(
            self.config.vision_model,
            tools=tools,
        )

        base_prompt = """
You are a sales team helper AI assistant providing real-time guidance during customer meetings.

You will be given:
- Recent meeting context (events + transcript from the last few seconds)
- Customer intent: Global analysis of customer from onboarding - what they were/are/will be looking for
- Recent interactions: Context from multiple sources (Slack, Gmail, Zendesk, Salesforce, etc.)
- Optional knowledge base snippets (company policies, product information)

Your task is to provide **strategic sales guidance** to help the sales person navigate this moment in the meeting.

Guidelines for your guidance:
- **Be strategic**: Consider the customer's journey, intent, and recent interactions when suggesting what to do
- **Be helpful**: If the customer faces an issue or asks a question, help resolve it quickly using the knowledge base, then guide the sales person to pivot back to value discussion
- **Be contextual**: Reference specific details from the customer's history when relevant
- **Be concise**: Keep guidance to 2-4 bullet points or a few sentences
- **Focus on guidance**: Tell the sales person WHAT to say or do, not just what's happening

Examples of good guidance:
- "Customer is asking about [feature]. Based on their Salesforce opportunity stage (Negotiation) and recent pricing questions, emphasize ROI and show how this feature addresses their specific use case mentioned in last week's email."
- "They're encountering an error. Use knowledge base to provide the fix immediately, then transition to discussing the premium support tier they were curious about."
- "Customer intent shows they're comparing with competitors. This is the moment to highlight our unique [specific differentiator] that directly addresses their core need."
""".strip()

        # Fetch and format analytics context from storage
        customer_summary = await self._format_customer_summary(storage)
        recent_interactions = await self._format_recent_interactions(storage)

        full_prompt = f"""{base_prompt}

Time window: from {window_start:.1f}s to {window_end:.1f}s (meeting-relative)

CONTEXT:
1. Customer Summary (Health, Sentiment, Intent, Risks, Opportunities):
{customer_summary}

2. Recent Interactions (from Slack, Gmail, Zendesk, Salesforce, etc.):
{recent_interactions}

3. Recent meeting context (what just happened in the meeting):
{joined_context}

You may call the `search_knowledge_base` tool if you need to look up:
- Company policies, terms, pricing ("company_data")
- Product features, specs, troubleshooting ("products")

Based on what's happening in the meeting right now, the customer's health/sentiment/intent, and their recent interactions, provide strategic guidance for the sales person on:
- What to say or do next to move the deal forward
- How to address the current situation based on customer's health score and sentiment
- How to leverage this moment considering their risks and opportunities
""".strip()

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
                # Mocking the actual search call for now as per instructions
                # In real implementation: matches = store.search_similar_issues(query, top_k=top_k)
                return f"[Mock Result from {index_name}] Search for '{query}' returned no results or mocked data."
                
            except Exception as e:
                logger.error(f"[SuggestionService] Error querying Pinecone index {index_name}: {e}")
                return f"Error while searching {index_name}: {e}"

        # Simple tool-calling loop: allow the model to request tools at most once
        # before producing a final answer.
        try:
            response = await model.generate_content_async(full_prompt)

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
                    # args may be a dict or JSON-like structure
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
                    # Ask the model again, now with the tool outputs appended.
                    response = await model.generate_content_async([
                        {"text": full_prompt},
                        *tool_results,
                    ])

            suggestion_text = (getattr(response, "text", None) or "").strip()
        except Exception:
            logger.exception("[SuggestionService] Error calling Gemini suggestion model with tools")
            return (
                "Failed to generate a suggestion from the model. "
                "Please try again or check server logs for details."
            )

        if not suggestion_text:
            suggestion_text = (
                "The suggestion model returned no text. This may indicate an internal "
                "error or misconfiguration."
            )

        return suggestion_text
