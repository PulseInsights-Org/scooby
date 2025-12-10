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

    def _find_latest_screenshare_event(
        self,
        events_path: str,
    ) -> Optional[Tuple[str, str]]:
        """Return (event_text, participant_name) for the latest screenshare event.

        Heuristic: last event whose description clearly suggests screen sharing
        or presenting, using a broader set of phrases such as:
          - "screen share", "screenshare", "screen-sharing"
          - "share screen", "sharing my screen", "sharing the screen"
          - "presenting", "present my screen", "presenting my screen"
          - "present screen", "present the screen"
        """
        try:
            latest_event: Optional[Tuple[str, str]] = None
            keywords = [
                "screen share",
                "screenshare",
                "screen-sharing",
                "share screen",
                "sharing my screen",
                "sharing the screen",
                "sharing your screen",
                "sharing their screen",
                "presenting my screen",
                "presenting your screen",
                "presenting the screen",
                "present my screen",
                "present your screen",
                "present screen",
                "present the screen",
                "presenting",
            ]

            with open(events_path, "r", encoding="utf-8") as f:
                for line in f:
                    parsed = self._parse_event_line(line)
                    if not parsed:
                        continue
                    _ts, event_desc, person = parsed
                    text_lower = event_desc.lower()
                    if any(kw in text_lower for kw in keywords):
                        latest_event = (event_desc, person)

            return latest_event
        except FileNotFoundError:
            logger.debug("[ScreenAnalysisService] Events file not found: %s", events_path)
            return None
        except Exception:
            logger.exception(
                "[ScreenAnalysisService] Error while scanning events file for screenshare events: %s",
                events_path,
            )
            return None

    async def analyze_latest_screenshare(
        self,
        *,
        bot_id: str,
        storage: SummaryStorage,
    ) -> Optional[str]:
        """Run vision-based analysis for the latest screenshare event.

        Returns a human-readable analysis string, or None/short message if
        no suitable context/frames are available.
        """
        if not bot_id or not storage:
            return None

        events_path = storage.get_events_path()
        latest = self._find_latest_screenshare_event(events_path)
        if not latest:
            logger.info(
                "[ScreenAnalysisService] No screenshare-related events found in %s",
                events_path,
            )
            return (
                "No screenshare-related events have been detected yet in the meeting "
                "timeline. Try sharing your screen and describing the issue, then run /capture again."
            )

        event_text, participant_name = latest
        logger.info(
            "[ScreenAnalysisService] Using latest screenshare event by '%s': %s",
            participant_name,
            event_text,
        )

        # Fetch frames for this bot + participant
        max_frames = self.config.vision_max_images_per_request
        frames: List[Dict[str, Any]] = self.buffer.get_recent_frames_for_bot_and_participant(
            bot_id=bot_id,
            participant_name=participant_name,
            max_frames=max_frames,
        )

        if not frames:
            logger.info(
                "[ScreenAnalysisService] No recent frames found in Redis for bot_id=%s, participant=%s",
                bot_id,
                participant_name,
            )
            return (
                "No recent screenshare frames were found for the participant "
                f"'{participant_name}'. Make sure they are actively sharing their "
                "screen while describing the issue, then run /capture again."
            )

        if not self.config.vision_enabled or not self.config.gemini_api_key:
            logger.error("[ScreenAnalysisService] Vision disabled or GEMINI_API_KEY missing")
            return (
                "Vision-based analysis is not enabled or GEMINI_API_KEY is missing on "
                "the server. Please contact the system administrator."
            )

        # Configure Gemini client
        genai.configure(api_key=self.config.gemini_api_key)
        model = genai.GenerativeModel(self.config.vision_model)

        base_prompt = """
You are an expert technical assistant helping debug issues based on what is shown
on the user's shared screen. You will be given several PNG frames captured from
the call, plus a short description of what the participant is saying.

Your job is to:
1) Carefully inspect the UI, error messages, and visible configuration.
2) Infer what the participant is trying to do and why it might be failing.
3) Provide a concise but practical analysis that would help a teammate debug or
   guide the user.

IMPORTANT CONSTRAINTS:
- Use the spoken event description as the primary definition of the "problem".
- ONLY describe and reason about on-screen elements that are clearly related to
  that problem.
- If you see windows, tabs, or applications that appear unrelated to the
  described event/problem, IGNORE them completely and do NOT mention them.
- If you are unsure whether some on-screen detail is relevant, leave it out.

Be concrete and reference any visible error codes, endpoints, HTTP status
codes, or obvious misconfigurations on screen that are clearly tied to the
described event/problem.
""".strip()

        full_prompt = f"""{base_prompt}

Latest screenshare event description (spoken context):
Speaker: {participant_name}
Event: {event_text}

Now analyze ONLY the parts of the frames that are clearly connected to this
event/problem, and summarize the most important insights that would help debug
or assist the participant.
""".strip()

        # Build image parts for Gemini
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
            logger.error("[ScreenAnalysisService] Failed to build image parts from frames")
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
            logger.exception("[ScreenAnalysisService] Error calling Gemini vision model")
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
