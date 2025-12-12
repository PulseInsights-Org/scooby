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
        model = genai.GenerativeModel(self.config.vision_model)

        base_prompt = """
You are an expert debugging assistant. You are given:
- A few PNG frames from the user's shared screen, and
- A short window of spoken context describing the problem.

Your job is NOT to describe the screen. Your job is to:
1) Identify the most likely root cause of the problem.
2) Propose 2–4 very concrete steps the user should take to fix or debug it.

Guidelines:
- Focus on actionable suggestions (what to change in request body, headers,
  configuration, timestamp format, etc.), not long prose.
- Use the on-screen error messages and context to infer what is wrong.
- If multiple fixes are possible, list them in order of likelihood.
- Keep the answer short and crisp: no more than a few sentences or bullet
  points.
- Do NOT repeat the entire error message; only reference the key parts needed
  to explain the fix.
""".strip()

        window_text = "\n".join(context_lines)
        full_prompt = f"""{base_prompt}

Time window: from {window_start:.1f}s to {window_end:.1f}s (meeting-relative)

Spoken/context in this window:
Speaker: {participant_name}
{window_text}

Based ONLY on what is relevant to this window of context and the visible
on-screen details, write a very short answer that:
- Names the most likely cause of the problem, and
- Lists 2–4 specific, practical steps the user should take next to resolve or
  debug it.
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

        try:
            response = await model.generate_content_async([
                {"text": full_prompt},
                *image_parts,
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
