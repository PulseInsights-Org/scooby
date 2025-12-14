import asyncio
from typing import Any, Dict, Optional
import logging

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
        self._logger = logging.getLogger(__name__)
        self._client: Optional[Client]

        if not url or not service_role_key:
            # Store is effectively disabled if config is missing
            self._client = None
            return

        self._client = create_client(url, service_role_key)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def ensure_meeting_row(
        self,
        *,
        org_name: str,
        bot_id: str,
        meeting_url: Optional[str],
    ) -> None:
        """Ensure a meeting row exists as soon as the bot is created.

        Creates or upserts a row with org_name, bot_id, meeting_url and
        leaves summary/status as NULL until they are populated later by
        other upsert calls.
        """
        if not self._client:
            return

        payload: Dict[str, Any] = {
            "org_name": org_name,
            "bot_id": bot_id,
            "meeting_url": meeting_url,
            # Let DB default / stay NULL for these until updated later
            "summary": None,
            "status": None,
        }

        def _do_upsert() -> None:
            self._client.table(self._table_name).upsert(
                payload,
                on_conflict="org_name,bot_id",
            ).execute()

        try:
            await asyncio.to_thread(_do_upsert)
            self._logger.info(
                "[Supabase] ensure_meeting_row upsert OK org=%s bot=%s",
                org_name,
                bot_id,
            )
        except Exception as e:
            self._logger.exception(
                "[Supabase] ensure_meeting_row failed org=%s bot=%s: %s",
                org_name,
                bot_id,
                e,
            )
            raise

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
            return

    async def upsert_status(
        self,
        *,
        org_name: str,
        bot_id: str,
        status: str,
    ) -> None:
        if not self._client:
            return

        payload: Dict[str, Any] = {
            "org_name": org_name,
            "bot_id": bot_id,
            "status": status,
        }

        def _do_upsert() -> None:
            self._client.table(self._table_name).upsert(
                payload,
                on_conflict="org_name,bot_id",
            ).execute()

        try:
            await asyncio.to_thread(_do_upsert)
        except Exception:
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
            except Exception as e:
                self._logger.exception(
                    "[Supabase] get_current_summary failed org=%s bot=%s: %s",
                    org_name,
                    bot_id,
                    e,
                )
                return None

        return await asyncio.to_thread(_do_select)
