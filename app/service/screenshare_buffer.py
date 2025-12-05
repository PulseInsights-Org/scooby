import os
import json
from typing import Any, Dict

import redis


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
