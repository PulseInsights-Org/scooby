import os
from typing import Callable, Optional, Awaitable
import logging
import asyncio
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)


class TranscriptWriter:
    """
    Handles writing transcript lines to disk, controlled by an enable flag.

    Parameters:
    - enabled_getter: Callable[[], bool] that returns whether writing is enabled
    - transcripts_dir: directory path where transcripts are stored
    - meeting_url_getter: Callable[[], str | None] to fetch current meeting url for naming
    """

    def __init__(
        self,
        enabled_getter: Callable[[], bool],
        transcripts_dir: str,
        meeting_url_getter: Callable[[], str | None],
        org_name = None
    ):
        self._enabled_getter = enabled_getter
        self._dir = transcripts_dir
        self._meeting_url_getter = meeting_url_getter
        self.org_name = org_name
        self.id = str(uuid.uuid4())[:4]
        try:
            os.makedirs(self._dir, exist_ok=True)
        except Exception:
            pass

    def save_line(self, speaker: str, text: str) -> None:
        try:
            if not self._enabled_getter():
                return
            if not os.path.exists(self._dir):
                os.makedirs(self._dir, exist_ok=True)
            file_path = os.path.join(self._dir, f"Scooby_{self.org_name}_{self.id}.txt")
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(f"{speaker}: {text}\n")
        except Exception as e:
            logger.exception(f"Error saving transcript: {e}")


class BotContext:
    """Holds current bot state and transcript toggle.

    Note: wiring resets of external model should be handled by the caller.
    """

    def __init__(self):
        self.bot_id = None
        self.meeting_url = None
        self.transcripts_enabled = False

    def clear(self):
        self.bot_id = None
        self.meeting_url = None
        self.transcripts_enabled = False

    def is_transcripts_enabled(self) -> bool:
        return bool(self.transcripts_enabled)

    @staticmethod
    def safe_name(value: str) -> str:
        try:
            s = str(value or "unknown")
            for ch in '<>:"/\\|?*':
                s = s.replace(ch, '-')
            return s.strip().replace(os.sep, '-')
        except Exception:
            return "unknown"

    @staticmethod
    def remove_model_context(model: object) -> None:
        """Reset bot-related context on the Gemini model safely."""
        try:
            model.bot_id = None
            model.chat_history = []
            model.conversation_history = []
            try:
                model.current_transcription = ""
            except Exception:
                pass
        except Exception:
            pass

    def print_active_bot(self) -> None:
        try:
            logger.info(f"Current active bot: {self.bot_id}")
        except Exception as e:
            logger.exception(f"Error printing active bots: {e}")

    # Shared guard to avoid duplicate ingestions per bot
    _transcript_ingestion_lock = asyncio.Lock()
    _transcript_ingested_bots = set()

    @staticmethod
    async def ingest_and_cleanup_transcript(
        bot_id: str,
        *,
        transcripts_enabled: bool,
        transcripts_dir: str,
        meeting_url: str | None,
        ti,  # TranscriptIngestion instance
        x_org_name: str,
        transcript_writer,  # TranscriptWriter instance
        logger: logging.Logger,
    ) -> None:
        try:
            if not transcripts_enabled:
                return
            # Build transcript file path to match TranscriptWriter.save_line naming
            # => "Scooby_{org_name}_{writer.id}.txt"
            transcript_path = os.path.join(
                transcripts_dir,
                f"Scooby_{x_org_name}_{getattr(transcript_writer, 'id', 'unknown')}.txt",
            )

            # Ensure only one ingestion per bot
            async with BotContext._transcript_ingestion_lock:
                if bot_id in BotContext._transcript_ingested_bots:
                    logger.info("Transcript ingestion already performed for bot %s; skipping", bot_id)
                    return
                BotContext._transcript_ingested_bots.add(bot_id)

            if not os.path.exists(transcript_path):
                logger.warning("Transcript file not found at %s", transcript_path)
                return

            logger.info("Starting transcript ingestion for %s", transcript_path)
            res = await ti.ingest_transcript(x_org_name, transcript_path)
            logger.info("Transcript ingestion result: %s", res)

            if res and res.get("success"):
                try:
                    os.remove(transcript_path)
                    logger.info("Deleted transcript file %s", transcript_path)
                except Exception as de:
                    logger.error("Failed to delete transcript file %s: %s", transcript_path, de)
        except Exception as e:
            logger.exception("Error during transcript ingestion: %s", e)


class InactivityMonitor:
    """Reusable inactivity monitor with OR-logic removal conditions.

    Conditions:
    - No human participants for NO_PARTICIPANTS_GRACE_SECONDS
    - OR no transcripts for NO_TRANSCRIPTS_GRACE_SECONDS

    Configuration (env with defaults):
    - SCOOBY_INACTIVITY_POLL_SECONDS (default 10)
    - SCOOBY_NO_PARTICIPANTS_GRACE_SECONDS (default 120)
    - SCOOBY_NO_TRANSCRIPTS_GRACE_SECONDS (default 300)
    """

    def __init__(
        self,
        *,
        get_current_bot_id: Callable[[], Optional[str]],
        participants_manager,
        model,
        transcript_writer: TranscriptWriter,
        bot_name: str = "scooby",
        remove_bot: Callable[[str], Awaitable[dict]],
        on_cleared: Callable[[], None],
    ) -> None:
        self._get_bot_id = get_current_bot_id
        self._pm = participants_manager
        self._model = model
        self._tw = transcript_writer
        self._bot_name = bot_name.lower()
        self._remove_bot = remove_bot
        self._on_cleared = on_cleared

        self._last_activity_at: Optional[datetime] = None
        self._last_transcript_at: Optional[datetime] = None
        self._task: Optional[asyncio.Task] = None

        # Load from env
        self.POLL_SECONDS = int(os.getenv("SCOOBY_INACTIVITY_POLL_SECONDS", "10"))
        self.NO_PARTICIPANTS_GRACE_SECONDS = int(os.getenv("SCOOBY_NO_PARTICIPANTS_GRACE_SECONDS", "120"))
        self.NO_TRANSCRIPTS_GRACE_SECONDS = int(os.getenv("SCOOBY_NO_TRANSCRIPTS_GRACE_SECONDS", "300"))

    def record_activity(self) -> None:
        self._last_activity_at = datetime.now(timezone.utc)

    def record_transcript(self) -> None:
        self._last_transcript_at = datetime.now(timezone.utc)

    def _active_participants_count(self) -> int:
        try:
            return sum(
                1
                for p in self._pm.list
                if p.get("status") != "left" and str(p.get("name", "")).lower() != self._bot_name
            )
        except Exception:
            return 0

    async def _watch(self, expected_bot_id: str):
        logger.info(
            f"Starting inactivity watcher for bot {expected_bot_id} (poll={self.POLL_SECONDS}s, no-participants={self.NO_PARTICIPANTS_GRACE_SECONDS}s, no-transcripts={self.NO_TRANSCRIPTS_GRACE_SECONDS}s)"
        )
        try:
            while True:
                # stop if bot changed/cleared
                if self._get_bot_id() != expected_bot_id:
                    logger.debug("Inactivity watcher stopping: bot changed/cleared")
                    return

                await asyncio.sleep(self.POLL_SECONDS)

                now = datetime.now(timezone.utc)
                no_participants = self._active_participants_count() == 0
                idle_for_any = (now - (self._last_activity_at or now)).total_seconds()
                idle_for_transcripts = (now - (self._last_transcript_at or now)).total_seconds()

                if no_participants and idle_for_any >= self.NO_PARTICIPANTS_GRACE_SECONDS:
                    logger.info(
                        f"No participants for {idle_for_any:.0f}s (>= {self.NO_PARTICIPANTS_GRACE_SECONDS}). Removing bot {expected_bot_id}."
                    )
                    await self._remove_and_cleanup(expected_bot_id, reason="Removed due to inactivity (no participants)")
                    return

                if idle_for_transcripts >= self.NO_TRANSCRIPTS_GRACE_SECONDS:
                    logger.info(
                        f"No transcripts for {idle_for_transcripts:.0f}s (>= {self.NO_TRANSCRIPTS_GRACE_SECONDS}). Removing bot {expected_bot_id}."
                    )
                    await self._remove_and_cleanup(expected_bot_id, reason="Removed due to inactivity (no transcripts)")
                    return
        finally:
            self._task = None

    async def _remove_and_cleanup(self, bot_id: str, *, reason: str) -> None:
        try:
            await self._remove_bot(bot_id)
            try:
                self._tw.save_line(bot_id, "BOT_STATUS", reason)
            except Exception:
                pass
            try:
                self._pm.reset()
                self._model.participants = []
            except Exception:
                pass
            try:
                self._on_cleared()
            except Exception:
                pass
        except Exception as e:
            logger.exception("Failed to remove bot on inactivity: %s", e)

    def start(self, bot_id: str) -> None:
        # Initialize timers
        self.record_activity()
        self.record_transcript()
        # Restart task if running
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._watch(bot_id))

    def stop(self) -> None:
        try:
            if self._task is not None:
                self._task.cancel()
        finally:
            self._task = None
