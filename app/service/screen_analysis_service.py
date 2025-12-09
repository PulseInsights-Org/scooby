import os
import json
import logging
from typing import Any, Dict, List, Optional

import redis


logger = logging.getLogger(__name__)


class ScreenAnalysisService:
    """Service for analyzing recent screenshare frames from Redis.

    Frames are written by ScreenshareRedisBuffer using keys of the form:
        screenshare:{bot_id}:{participant_id}

    Each list item is a JSON blob with:
      - org_name
      - bot_id
      - participant_id
      - participant_name
      - timestamp_absolute
      - timestamp_relative
      - hash
      - image_base64

    This service fetches recent frames around a time window and returns
    a human-readable analysis string that can be sent to Slack.
    """

    def __init__(self) -> None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = redis.from_url(redis_url, decode_responses=True)

    def _load_frames_for_bot(
        self,
        *,
        bot_id: str,
        participant_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Load all frames for a given bot (and optional participant) from Redis.

        NOTE: This is synchronous but uses simple Redis list operations, which
        should be fast given the bounded buffer size.
        """

        frames: List[Dict[str, Any]] = []

        if participant_id:
            keys = [f"screenshare:{bot_id}:{participant_id}"]
        else:
            pattern = f"screenshare:{bot_id}:*"
            keys = list(self._redis.scan_iter(match=pattern))

        for key in keys:
            try:
                items = self._redis.lrange(key, 0, -1)
            except Exception as e:
                logger.warning("[ScreenAnalysis] Failed to read key %s: %s", key, e)
                continue

            for raw in items:
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        frames.append(data)
                except Exception:
                    continue

        return frames

    def _select_time_window(
        self,
        frames: List[Dict[str, Any]],
        window_seconds: float,
    ) -> List[Dict[str, Any]]:
        """Select frames in the last `window_seconds` based on timestamp_relative."""

        rel_times = [f.get("timestamp_relative") for f in frames if f.get("timestamp_relative") is not None]
        if not rel_times:
            return []

        end_rel = max(rel_times)
        start_rel = max(0.0, end_rel - window_seconds)

        in_window: List[Dict[str, Any]] = []
        for f in frames:
            t = f.get("timestamp_relative")
            if t is None:
                continue
            try:
                t_float = float(t)
            except (TypeError, ValueError):
                continue
            if start_rel <= t_float <= end_rel:
                in_window.append(f)

        return in_window

    async def analyze_recent_screens(
        self,
        *,
        bot_id: str,
        participant_id: Optional[str] = None,
        window_seconds: float = 10.0,
    ) -> str:
        """Analyze recent screenshare frames for a bot/participant.

        Currently this returns a lightweight textual analysis based on metadata.
        You can later plug in a vision model here that consumes `image_base64`.
        """

        frames = self._load_frames_for_bot(bot_id=bot_id, participant_id=participant_id)
        if not frames:
            return "No recent screenshare frames available for analysis."

        recent_frames = self._select_time_window(frames, window_seconds=window_seconds)
        if not recent_frames:
            return "No screenshare frames found in the recent analysis window."

        # Group by participant
        by_participant: Dict[str, List[Dict[str, Any]]] = {}
        for f in recent_frames:
            pid = str(f.get("participant_id") or "unknown")
            by_participant.setdefault(pid, []).append(f)

        lines: List[str] = []
        lines.append("Screenshare analysis for the last %.1f seconds:" % window_seconds)

        for pid, frames_list in by_participant.items():
            name = frames_list[0].get("participant_name") or pid
            count = len(frames_list)
            start_t = min(fl.get("timestamp_relative") or 0.0 for fl in frames_list)
            end_t = max(fl.get("timestamp_relative") or 0.0 for fl in frames_list)
            lines.append(
                f"- Participant {name} (ID: {pid}) had {count} unique frames between t={start_t:.1f}s and t={end_t:.1f}s."
            )

        # Placeholder for future vision model output
        lines.append("")
        lines.append("(Vision model integration pending: this is a metadata-based summary only.)")

        return "\n".join(lines)
