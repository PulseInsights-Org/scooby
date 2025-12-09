import os
import json
import logging
from typing import Any, Dict, List, Optional

import redis

from app.service.gemini_vision_service import GeminiVisionService


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

    This service fetches recent frames around a time window and uses
    Gemini Vision to analyze the visual content.
    """

    def __init__(self) -> None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._vision_service = GeminiVisionService()

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

    def _select_representative_frames(
        self,
        frames: List[Dict[str, Any]],
        max_frames: int = 10  # Increased from 5 to 10
    ) -> List[Dict[str, Any]]:
        """Select representative frames from the window for analysis.
        
        Strategy: Select evenly distributed frames (start, middle, end, etc.)
        to get a good overview without analyzing every frame.
        """
        
        if len(frames) <= max_frames:
            return frames
        
        # Sort by timestamp
        sorted_frames = sorted(frames, key=lambda f: f.get("timestamp_relative", 0.0))
        
        # Select evenly distributed indices
        indices = []
        step = len(sorted_frames) / max_frames
        for i in range(max_frames):
            idx = int(i * step)
            indices.append(idx)
        
        selected = [sorted_frames[i] for i in indices]
        logger.info(f"Selected {len(selected)} representative frames from {len(frames)} total")
        
        return selected

    def _format_time_range(self, frames: List[Dict[str, Any]]) -> str:
        """Format the time range of frames for display"""
        
        if not frames:
            return "N/A"
        
        times = [f.get("timestamp_relative", 0.0) for f in frames]
        start_t = min(times)
        end_t = max(times)
        
        def format_seconds(seconds: float) -> str:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}:{secs:02d}"
        
        return f"{format_seconds(start_t)} - {format_seconds(end_t)}"

    def _build_rich_context(
        self,
        frames: List[Dict[str, Any]],
        bot_id: str,
        participant_id: Optional[str] = None
    ) -> str:
        """Build rich context for vision analysis with meeting and participant details"""
        
        context_parts = []
        
        # Add meeting context
        context_parts.append(f"Meeting Session ID: {bot_id}")
        
        # Add participant information
        if frames:
            first_frame = frames[0]
            org_name = first_frame.get("org_name")
            participant_name = first_frame.get("participant_name")
            
            if org_name:
                context_parts.append(f"Organization: {org_name}")
            
            if participant_name:
                context_parts.append(f"Presenter: {participant_name}")
            elif participant_id:
                context_parts.append(f"Participant ID: {participant_id}")
        
        # Add frame timeline information
        if len(frames) > 1:
            time_range = self._format_time_range(frames)
            context_parts.append(f"Time Range: {time_range}")
            context_parts.append(f"Analyzing {len(frames)} frames from the screenshare session")
        
        # Add analysis instructions
        context_parts.append(
            "Please provide detailed analysis of the visual content, "
            "including any code, diagrams, presentations, or technical content visible. "
            "Extract any visible text, identify UI elements, and note technical context "
            "such as programming languages, frameworks, or tools being used."
        )
        
        return ". ".join(context_parts)

    async def analyze_recent_screens(
        self,
        *,
        bot_id: str,
        participant_id: Optional[str] = None,
        window_seconds: float = 10.0,
    ) -> str:
        """Analyze recent screenshare frames for a bot/participant using Gemini Vision.

        Args:
            bot_id: The bot ID
            participant_id: Optional specific participant to analyze
            window_seconds: Time window to analyze (default 10 seconds)

        Returns:
            Formatted analysis string for Slack
        """

        # Load frames from Redis
        frames = self._load_frames_for_bot(bot_id=bot_id, participant_id=participant_id)
        if not frames:
            return "No recent screenshare frames available for analysis."

        # Filter to time window
        recent_frames = self._select_time_window(frames, window_seconds=window_seconds)
        if not recent_frames:
            return "No screenshare frames found in the recent analysis window."

        # Select representative frames for analysis (now 10 frames)
        frames_to_analyze = self._select_representative_frames(recent_frames, max_frames=10)
        
        logger.info(
            f"Analyzing {len(frames_to_analyze)} frames from {len(recent_frames)} "
            f"in window (total {len(frames)} frames in Redis)"
        )

        # Build rich context with meeting and participant details
        context = self._build_rich_context(
            frames=frames_to_analyze,
            bot_id=bot_id,
            participant_id=participant_id
        )

        # Analyze with Gemini Vision
        analysis = await self._vision_service.analyze_frames(
            frames=frames_to_analyze,
            context=context
        )

        # Format for Slack
        time_range = self._format_time_range(frames_to_analyze)
        result = self._vision_service.format_for_slack(
            analysis=analysis,
            frame_count=len(frames_to_analyze),
            time_range=time_range
        )

        return result


