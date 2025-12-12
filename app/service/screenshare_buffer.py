import os
import json
from typing import Any, Dict

import logging
import redis


logger = logging.getLogger(__name__)


class ScreenshareRedisBuffer:
    """Redis-backed bounded buffer for screenshare frames per bot+participant.

    Stores base64-encoded PNG frames plus metadata in a Redis list:
    key = f"screenshare:{bot_id}:{participant_id}"

    Each list item is a JSON blob with:
      - org_name
      - bot_id
      - participant_id
      - participant_name
      - timestamp_absolute
      - timestamp_relative
      - hash
      - image_base64
    """

    def __init__(self) -> None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = redis.from_url(redis_url, decode_responses=True)

        # Max number of frames per participant buffer
        try:
            self._max_size = int(os.getenv("SCREENSHARE_BUFFER_SIZE", "100"))
        except ValueError:
            self._max_size = 100

        # TTL in seconds for each buffer key
        try:
            self._ttl_seconds = int(os.getenv("SCREENSHARE_TTL_SECONDS", "3600"))
        except ValueError:
            self._ttl_seconds = 3600

    async def push_frame(
        self,
        *,
        org_name: str,
        bot_id: str,
        participant_id: str,
        participant_name: str | None,
        ts_absolute: str | None,
        ts_relative: float | None,
        img_hash: str,
        image_base64: str,
    ) -> None:
        """Push a frame into the Redis list for this bot+participant.

        Uses LPUSH + LTRIM to maintain a bounded buffer, and EXPIRE to enforce TTL.
        """
        key = f"screenshare:{bot_id}:{participant_id}"

        payload: Dict[str, Any] = {
            "org_name": org_name,
            "bot_id": bot_id,
            "participant_id": participant_id,
            "participant_name": participant_name,
            "timestamp_absolute": ts_absolute,
            "timestamp_relative": ts_relative,
            "hash": img_hash,
            "image_base64": image_base64,
        }

        # Use pipeline for atomic LPUSH/LTRIM/EXPIRE
        pipe = self._redis.pipeline()
        pipe.lpush(key, json.dumps(payload))
        pipe.ltrim(key, 0, self._max_size - 1)
        if self._ttl_seconds > 0:
            pipe.expire(key, self._ttl_seconds)
        pipe.execute()

    def get_recent_frames_for_bot(self, bot_id: str, max_frames: int = 10) -> list[Dict[str, Any]]:
        """Return up to max_frames most recent frames across all participants for a bot.

        This scans keys of the form "screenshare:{bot_id}:*" and merges their
        lists, ordered from newest to oldest based on Redis list order.

        This is a synchronous helper intended for use inside async paths that
        can tolerate a small blocking Redis call.
        """

        if not bot_id:
            return []

        pattern = f"screenshare:{bot_id}:*"
        frames: list[Dict[str, Any]] = []

        # Use SCAN to avoid blocking Redis with KEYS in large deployments
        cursor: int | str = 0
        while True:
            cursor, keys = self._redis.scan(cursor=cursor, match=pattern, count=50)
            for key in keys:
                # LRANGE returns list with most recent element at index 0 (because we LPUSH)
                raw_items = self._redis.lrange(key, 0, max_frames - 1)
                for raw in raw_items:
                    try:
                        payload = json.loads(raw)
                        frames.append(payload)
                    except Exception:
                        continue

            if cursor == 0 or len(frames) >= max_frames:
                break

        # We LPUSH per participant list, so global order is approximate. To
        # keep it simple, just truncate to max_frames.
        return frames[:max_frames]

    def get_recent_frames_for_bot_and_participant(
        self,
        bot_id: str,
        participant_name: str,
        max_frames: int = 10,
    ) -> list[Dict[str, Any]]:
        """Return up to max_frames recent frames for a specific participant in a bot.

        Filters frames by case-insensitive participant_name match using the
        stored "participant_name" field in each payload.
        """

        if not bot_id or not participant_name:
            return []

        all_frames = self.get_recent_frames_for_bot(bot_id, max_frames=max_frames * 3)
        name_lower = participant_name.lower()
        filtered: list[Dict[str, Any]] = []

        for frame in all_frames:
            pn = (frame.get("participant_name") or "").lower()
            if name_lower in pn:
                filtered.append(frame)
                if len(filtered) >= max_frames:
                    break

        return filtered

    def get_frames_for_bot_and_participant_near_time(
        self,
        bot_id: str,
        participant_name: str,
        center_ts: float,
        max_frames: int = 5,
    ) -> list[Dict[str, Any]]:
        """Return up to max_frames frames near a given time for a participant.

        Uses the stored "timestamp_relative" field to select frames that occurred
        at or before the given meeting-relative timestamp, ordering by recency.
        """

        if not bot_id or not participant_name or center_ts is None:
            return []

        # Fetch more frames than needed and then filter/sort by time.
        all_frames = self.get_recent_frames_for_bot(bot_id, max_frames=max_frames * 5)
        name_lower = participant_name.lower()
        candidates: list[Dict[str, Any]] = []

        for frame in all_frames:
            pn = (frame.get("participant_name") or "").lower()
            if name_lower not in pn:
                continue

            ts_rel = frame.get("timestamp_relative")
            if ts_rel is None:
                continue

            if ts_rel <= center_ts:
                candidates.append(frame)

        if candidates:
            ts_values = [f.get("timestamp_relative") or 0.0 for f in candidates]
            logger.info(
                "[ScreenshareRedisBuffer] Candidate frames for bot_id=%s participant=%s around %.2fs: count=%d, ts_min=%.2f, ts_max=%.2f",
                bot_id,
                participant_name,
                center_ts,
                len(candidates),
                min(ts_values),
                max(ts_values),
            )
        else:
            logger.info(
                "[ScreenshareRedisBuffer] No candidate frames found for bot_id=%s participant=%s around %.2fs",
                bot_id,
                participant_name,
                center_ts,
            )

        candidates.sort(key=lambda f: f.get("timestamp_relative") or 0.0, reverse=True)

        selected = candidates[:max_frames]
        if selected:
            sel_ts = [f.get("timestamp_relative") or 0.0 for f in selected]
            logger.info(
                "[ScreenshareRedisBuffer] Returning %d frames for bot_id=%s participant=%s around %.2fs with timestamps=%s",
                len(selected),
                bot_id,
                participant_name,
                center_ts,
                sel_ts,
            )
        return selected
