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
                        "name": "search_issues_kb",
                        "description": (
                            "Search an issues knowledge base for similar past "
                            "incidents or troubleshooting steps based on the "
                            "current problem description."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": "Natural language description of the issue to search for.",
                                },
                                "top_k": {
                                    "type": "integer",
                                    "description": "Maximum number of similar issues to retrieve.",
                                },
                            },
                            "required": ["query"],
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
You are an expert assistant helping engineers debug issues during a live call.

You will be given:
- A short slice of recent meeting context (events + transcript), and
- Optional snippets from an issues knowledge base.

Your task is to produce a **very short**, **actionable** suggestion that helps
the helper-person advise the person who reported the issue.

Guidelines:
- Focus on the most recent issue being discussed (HTTP errors, failures, etc.).
- Propose 2–4 concrete steps or checks (what to inspect, change, or try next).
- Ground your advice in both the meeting context and any relevant KB snippets.
- Do not write a long explanation; keep it to a few sentences or bullet points.
- Do not repeat the entire error messages; reference only key parts.
""".strip()

        full_prompt = f"""{base_prompt}

Time window: from {window_start:.1f}s to {window_end:.1f}s (meeting-relative)

Recent meeting context (events + transcript):
{joined_context}

You may call the `search_issues_kb` tool if you think similar past issues
would help you produce a better suggestion.

Now, write a very short suggestion that:
- Identifies the most likely nature of the problem, and
- Lists 2–4 practical steps the helper should suggest to move forward.
""".strip()

        # Helper to execute the search_issues_kb tool when invoked by Gemini.
        async def _handle_tool_call(tool_name: str, args: dict) -> str:
            if tool_name != "search_issues_kb":
                return f"Unknown tool: {tool_name}"

            issues_store = getattr(self.summarization_service, "issues_pinecone_store", None)
            if not issues_store:
                return "Issues knowledge base is not available."

            query = args.get("query") or joined_context
            top_k = int(args.get("top_k") or 5)

            try:
                matches = issues_store.search_similar_issues(query, top_k=top_k)
                lines: List[str] = []
                for m in matches:
                    md = m.get("metadata", {}) or {}
                    text = (
                        md.get("title")
                        or md.get("summary")
                        or md.get("description")
                        or ""
                    )
                    if text:
                        lines.append(f"- {text}")
                return "\n".join(lines) if lines else "(No similar issues found in the knowledge base.)"
            except Exception as e:
                logger.error(f"[SuggestionService] Error querying issues Pinecone index: {e}")
                return f"Error while searching issues knowledge base: {e}"

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
