import os
import json
from typing import Optional

import redis.asyncio as redis


class ScreenshareRedisBuffer:
    """Redis-backed buffer for recent screenshare frames per bot+participant.

    Stores base64-encoded PNG frames with minimal metadata in a bounded list
    per (bot_id, participant_id). Each key also has a TTL so buffers expire
    automatically after inactivity.
    """

    def __init__(self) -> None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = redis.from_url(redis_url)

        # Max number of frames to keep per participant+bot
        self._max_size = int(os.getenv("SCREENSHARE_BUFFER_SIZE", "100"))
        # TTL for each buffer key in seconds (default: 1 hour)
        self._ttl_seconds = int(os.getenv("SCREENSHARE_TTL_SECONDS", "3600"))

    async def push_frame(
        self,
        *,
        org_name: str,
        bot_id: str,
        participant_id: str,
        participant_name: Optional[str],
        ts_absolute: Optional[str],
        ts_relative: Optional[float],
        img_hash: str,
        image_base64: str,
    ) -> None:
        """Append a frame to the participant buffer and enforce size + TTL."""
        key = f"screenshare:{bot_id}:{participant_id}"

        payload = {
            "org_name": org_name,
            "bot_id": bot_id,
            "participant_id": participant_id,
            "participant_name": participant_name,
            "timestamp_absolute": ts_absolute,
            "timestamp_relative": ts_relative,
            "hash": img_hash,
            "image_base64": image_base64,
        }
        data = json.dumps(payload)

        pipe = self._redis.pipeline()
        pipe.lpush(key, data)
        pipe.ltrim(key, 0, self._max_size - 1)
        pipe.expire(key, self._ttl_seconds)
        await pipe.execute()
