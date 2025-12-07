import os
import base64
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

from app.core.config import get_config
from app.service.screenshare_metadata_store import ScreenshareMetadataStore


class ScreenshareS3:
    """S3-backed storage for screenshare frames plus Supabase metadata.

    For each deduplicated frame, uploads the PNG bytes to S3 and then
    writes a metadata row into Supabase via ScreenshareMetadataStore.

    S3 layout (by default):
      screenshares/{org}/{bot_id}/{participant_id}/
          {timestamp}_{hash}.png

    Configured via env vars:
      - SCREENSHARE_S3_BUCKET (required to enable uploads)
      - SCREENSHARE_S3_PREFIX (optional, default: "screenshares/")
      - AWS_REGION (optional, for boto3 client)
    """

    def __init__(self) -> None:
        config = get_config()
        self._bucket = getattr(config, "screenshare_s3_bucket", "").strip()
        self._prefix = getattr(config, "screenshare_s3_prefix", "screenshares/")

        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        if region:
            self._s3 = boto3.client("s3", region_name=region)
        else:
            # Region-less client will rely on AWS config/instance metadata
            self._s3 = boto3.client("s3")

        # Supabase-backed metadata store
        self._metadata_store = ScreenshareMetadataStore()

    def _sanitize(self, value: Optional[str]) -> str:
        if not value:
            return "unknown"
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in value)[:64]

    def _build_object_key(
        self,
        *,
        org_name: str,
        bot_id: str,
        participant_id: str,
        participant_name: Optional[str],
        ts_absolute: Optional[str],
        ts_relative: Optional[float],
        img_hash: str,
    ) -> str:
        org_safe = self._sanitize(org_name)
        bot_safe = self._sanitize(bot_id)
        participant_id_safe = self._sanitize(participant_id)
        participant_name_safe = self._sanitize(participant_name or participant_id)

        if ts_absolute:
            # Normalize ISO-like timestamp into filesystem/S3-safe form
            ts = (
                ts_absolute.replace(":", "")
                .replace("-", "")
                .replace(".", "_")
                .replace("Z", "z")
            )
        else:
            rel_str = f"{ts_relative:.3f}" if ts_relative is not None else "0.000"
            ts = f"rel_{rel_str.replace('.', '_')}"

        filename_base = f"{participant_name_safe}_{participant_id_safe}_{ts}_{img_hash}"
        # Ensure prefix always ends with '/'
        prefix = self._prefix
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"

        return f"{prefix}{org_safe}/{bot_safe}/{participant_id_safe}/{filename_base}.png"

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
        """Upload a frame to S3 and write metadata to Supabase.

        If SCREENSHARE_S3_BUCKET is not set, this is a no-op.
        """
        if not self._bucket:
            # S3 storage not configured; safely no-op
            return

        try:
            key = self._build_object_key(
                org_name=org_name,
                bot_id=bot_id,
                participant_id=participant_id,
                participant_name=participant_name,
                ts_absolute=ts_absolute,
                ts_relative=ts_relative,
                img_hash=img_hash,
            )

            # Decode image bytes
            image_bytes = base64.b64decode(image_base64)

            # Upload PNG frame
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=image_bytes,
                ContentType="image/png",
            )

            # Insert metadata row into Supabase (no JSON sidecar in S3)
            await self._metadata_store.insert_frame_metadata(
                org_name=org_name,
                bot_id=bot_id,
                participant_id=participant_id,
                participant_name=participant_name,
                ts_absolute=ts_absolute,
                ts_relative=ts_relative,
                img_hash=img_hash,
                s3_bucket=self._bucket,
                s3_key=key,
            )
        except Exception:
            # Fail silently; the Redis buffer path is the primary real-time dependency
            # Detailed logging should be handled by the caller if needed.
            return
