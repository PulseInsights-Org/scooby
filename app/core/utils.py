import os
from typing import Callable


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
    ):
        self._enabled_getter = enabled_getter
        self._dir = transcripts_dir
        self._meeting_url_getter = meeting_url_getter
        try:
            os.makedirs(self._dir, exist_ok=True)
        except Exception:
            pass

    def save_line(self, bot_id: str, speaker: str, text: str) -> None:
        try:
            if not self._enabled_getter():
                return
            if not os.path.exists(self._dir):
                os.makedirs(self._dir, exist_ok=True)
            safe_bot = BotContext.safe_name(bot_id)
            safe_meeting = BotContext.safe_name(self._meeting_url_getter() or "meeting")
            file_path = os.path.join(self._dir, f"{safe_bot}_{safe_meeting}.txt")
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(f"{speaker}: {text}\n")
        except Exception as e:
            print(f"Error saving transcript: {e}")


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
            print(f"Current active bot: {self.bot_id}")
        except Exception as e:
            print(f"Error printing active bots: {e}")
