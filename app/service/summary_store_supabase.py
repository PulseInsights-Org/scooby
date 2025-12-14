import asyncio
from typing import Any, Dict, Optional

from supabase import create_client, Client

from app.core.config import get_config


class MeetingSummaryStore:
    """Supabase-backed store for meeting-level summaries.

    Expected table schema (default table name: meeting_summaries):
      - org_name (text)
      - bot_id (text)
      - meeting_url (text, nullable)
      - summary (text)
      - updated_at (timestamptz, default now())

    There should be a unique constraint on (org_name, bot_id) so upserts
    keep a single row per meeting.
    """

    def __init__(self, table_name: str = "meeting_summaries") -> None:
        config = get_config()
        url = getattr(config, "supabase_url", "") or ""
        service_role_key = getattr(config, "supabase_service_role_key", "") or ""

        self._table_name: str = table_name
        self._client: Optional[Client]

        if not url or not service_role_key:
            # Store is effectively disabled if config is missing
            self._client = None
            return

        self._client = create_client(url, service_role_key)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def upsert_summary(
        self,
        *,
        org_name: str,
        bot_id: str,
        meeting_url: Optional[str],
        summary: str,
    ) -> None:
        """Upsert the current summary for a given meeting.

        This is async but uses a background thread because the Supabase
        Python client is synchronous.
        """
        if not self._client:
            return

        payload: Dict[str, Any] = {
            "org_name": org_name,
            "bot_id": bot_id,
            "meeting_url": meeting_url,
            "summary": summary,
        }

        def _do_upsert() -> None:
            self._client.table(self._table_name).upsert(
                payload,
                on_conflict="org_name,bot_id",
            ).execute()

        try:
            await asyncio.to_thread(_do_upsert)
        except Exception:
            # Fail silently; summarization pipeline should not break if Supabase fails
            return

    async def get_current_summary(
        self,
        *,
        org_name: str,
        bot_id: str,
    ) -> Optional[str]:
        """Fetch the latest summary for a given meeting from Supabase.

        Returns the summary text or None if not found / disabled / on error.
        """
        if not self._client:
            return None

        def _do_select() -> Optional[str]:
            try:
                resp = (
                    self._client
                    .table(self._table_name)
                    .select("summary")
                    .eq("org_name", org_name)
                    .eq("bot_id", bot_id)
                    .limit(1)
                    .single()
                    .execute()
                )
                data = getattr(resp, "data", None) or {}
                return data.get("summary")
            except Exception:
                return None

        return await asyncio.to_thread(_do_select)
