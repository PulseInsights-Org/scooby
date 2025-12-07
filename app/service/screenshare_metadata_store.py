import asyncio
from typing import Any, Dict, Optional, List, Tuple

from supabase import create_client, Client

from app.core.config import get_config


class ScreenshareMetadataStore:
    """Supabase-backed metadata store for screenshare frames.

    Inserts one row per deduplicated frame into a Supabase/Postgres table,
    so metadata can be queried quickly (e.g., by bot, participant, timestamps).

    Table schema expectation (default table name: screenshare_frames):
      - org_name (text)
      - bot_id (text)
      - participant_id (text)
      - participant_name (text, nullable)
      - timestamp_absolute (timestamptz or text)
      - timestamp_relative (double precision)
      - img_hash (text)
      - s3_bucket (text)
      - s3_key (text)
      - created_at (timestamptz, default now())
    """

    def __init__(self) -> None:
        config = get_config()
        url = getattr(config, "supabase_url", "") or ""
        service_role_key = getattr(config, "supabase_service_role_key", "") or ""
        table_name = getattr(config, "screenshare_metadata_table", "screenshare_frames")

        self._table_name: str = table_name
        self._client: Optional[Client]

        if not url or not service_role_key:
            # Metadata store is effectively disabled if config is missing
            self._client = None
            return

        self._client = create_client(url, service_role_key)

    async def insert_frame_metadata(
        self,
        *,
        org_name: str,
        bot_id: str,
        participant_id: str,
        participant_name: str | None,
        ts_absolute: str | None,
        ts_relative: float | None,
        img_hash: str,
        s3_bucket: str,
        s3_key: str,
    ) -> None:
        """Insert a single frame metadata row into Supabase.

        This method is async but uses a background thread to avoid blocking the
        event loop, since the Supabase Python client is synchronous.
        """
        if not self._client:
            # Not configured; safely no-op
            return

        payload: Dict[str, Any] = {
            "org_name": org_name,
            "bot_id": bot_id,
            "participant_id": participant_id,
            "participant_name": participant_name,
            "timestamp_absolute": ts_absolute,
            "timestamp_relative": ts_relative,
            "img_hash": img_hash,
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
        }

        async def _do_insert() -> None:
            # We ignore the return value; errors are allowed to bubble up
            self._client.table(self._table_name).insert(payload).execute()

        try:
            await asyncio.to_thread(lambda: self._client.table(self._table_name).insert(payload).execute())
        except Exception:
            # Fail silently; screenshare pipeline should not break if metadata insert fails
            return

    def query_frames_by_participant_and_window(
        self,
        *,
        participant_name: str,
        start_relative: float,
        end_relative: float,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Synchronously fetch frames for a participant within a relative time window.

        Returns (records, count), where each record is a dict with all columns
        from the underlying Supabase table.
        """
        if not self._client:
            return [], 0

        if end_relative < start_relative:
            start_relative, end_relative = end_relative, start_relative

        try:
            # Case-insensitive match on participant_name and time window filter
            query = (
                self._client
                .table(self._table_name)
                .select("*")
                .ilike("participant_name", f"%{participant_name}%")
                .gte("timestamp_relative", start_relative)
                .lte("timestamp_relative", end_relative)
                .order("timestamp_relative", desc=False)
            )

            resp = query.execute()
            records: List[Dict[str, Any]] = resp.data or []
            return records, len(records)
        except Exception:
            # On error, behave as empty result to avoid crashing callers
            return [], 0
