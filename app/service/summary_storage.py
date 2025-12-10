import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import logging
import aiofiles
from app.core.config import get_config

logger = logging.getLogger(__name__)

class SummaryStorage:
    """
    Manages file storage for transcripts, events, and summary.
    Maintains three files per meeting:
    - {org_name}_{meeting_id}_transcript.txt: Raw transcript lines (append)
    - {org_name}_{meeting_id}_events.txt: Event timeline (append)
    - {org_name}_{meeting_id}_summary.txt: Global MOM summary (replace)
    """

    def __init__(self, base_dir: str, org_name: str, meeting_id: str):
        self.config = get_config()
        self.base_dir = base_dir
        self.org_name = org_name
        self.meeting_id = meeting_id

        # Create directories
        self.transcripts_dir = os.path.join(base_dir, self.config.transcripts_dir)
        self.summaries_dir = os.path.join(base_dir, self.config.summaries_dir)

        os.makedirs(self.transcripts_dir, exist_ok=True)
        os.makedirs(self.summaries_dir, exist_ok=True)

        # File paths
        self.transcript_path = os.path.join(
            self.transcripts_dir,
            f"{org_name}_{meeting_id}{self.config.transcript_file_suffix}"
        )
        self.summary_path = os.path.join(
            self.summaries_dir,
            f"{org_name}_{meeting_id}{self.config.summary_file_suffix}"
        )
        self.events_path = os.path.join(
            self.summaries_dir,
            f"{org_name}_{meeting_id}{self.config.events_file_suffix}"
        )
        # Suggestions file will live alongside summary and events
        self.suggestions_path = os.path.join(
            self.summaries_dir,
            f"{org_name}_{meeting_id}_suggestions.txt",
        )
        # Screen analysis file (for screenshare-related analysis text)
        self.screen_analysis_path = os.path.join(
            self.summaries_dir,
            f"{org_name}_{meeting_id}_screen_analysis.txt",
        )

        logger.info(f"SummaryStorage initialized for {org_name}_{meeting_id}")
        logger.info(f"Transcript path: {self.transcript_path}")
        logger.info(f"Events path: {self.events_path}")
        logger.info(f"Summary path: {self.summary_path}")
        logger.info(f"Suggestions path: {self.suggestions_path}")
        logger.info(f"Screen analysis path: {self.screen_analysis_path}")

    async def save_transcript_line(
        self,
        speaker: str,
        text: str,
        start_timestamp: Optional[float] = None,
        end_timestamp: Optional[float] = None
    ) -> None:
        """
        Append raw transcript line to transcript file with Recall.ai timestamps

        Args:
            speaker: Participant name
            text: Transcribed text
            start_timestamp: Recall.ai relative start timestamp (seconds)
            end_timestamp: Recall.ai relative end timestamp (seconds)
        """
        try:
            # Format timestamps from Recall.ai (relative seconds from start of meeting)
            if start_timestamp is not None and end_timestamp is not None:
                # Convert seconds to readable format (MM:SS or HH:MM:SS)
                start_time_str = self._format_relative_timestamp(start_timestamp)
                end_time_str = self._format_relative_timestamp(end_timestamp)
                line = f"[{start_time_str}-{end_time_str}] {speaker}: {text}\n"
            else:
                # Fallback to manual timestamp if Recall.ai timestamps not available
                time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                line = f"[{time_str}] {speaker}: {text}\n"

            async with aiofiles.open(self.transcript_path, 'a', encoding='utf-8') as f:
                await f.write(line)

            logger.debug(f"Saved transcript line: {speaker}")

        except Exception as e:
            logger.exception(f"Error saving transcript line: {e}")

    async def append_events(self, events: List[Dict[str, Any]]) -> None:
        """
        Append extracted events to events timeline file

        Args:
            events: List of event dicts with 'timestamp', 'event', 'person' keys
        """
        try:
            if not events:
                logger.debug("No events to append")
                return

            lines = []
            for event in events:
                timestamp = event.get('timestamp', 'N/A')
                event_desc = event.get('event', 'N/A')
                person = event.get('person', 'N/A')
                lines.append(f"[{timestamp}] [{event_desc}] [by {person}]\n")

            async with aiofiles.open(self.events_path, 'a', encoding='utf-8') as f:
                await f.writelines(lines)

            logger.info(f"Appended {len(events)} events to {self.events_path}")

        except Exception as e:
            logger.exception(f"Error appending events: {e}")

    async def replace_summary(self, summary: str) -> None:
        """
        Replace entire summary file with updated global summary

        Args:
            summary: Complete updated meeting summary (MOM)
        """
        try:
            clean_summary = self._strip_summary_header(summary)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header = f"=== MEETING SUMMARY (Minutes of Meeting) ===\n"
            header += f"Last Updated: {timestamp}\n"
            header += f"{'='*60}\n\n"
            content = clean_summary.strip() + "\n"

            async with aiofiles.open(self.summary_path, 'w', encoding='utf-8') as f:
                await f.write(header)
                await f.write(content)

            logger.info(f"Replaced summary in {self.summary_path} ({len(summary)} chars)")

        except Exception as e:
            logger.exception(f"Error replacing summary: {e}")

    async def append_suggestion(self, suggestion: str) -> None:
        """Append a suggestion block to the suggestions file in summaries dir."""
        try:
            if not suggestion:
                return

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header = f"\n=== SUGGESTION @ {timestamp} ===\n"
            content = header + suggestion.strip() + "\n"

            async with aiofiles.open(self.suggestions_path, "a", encoding="utf-8") as f:
                await f.write(content)

            logger.info(f"Appended suggestion to {self.suggestions_path} ({len(suggestion)} chars)")

        except Exception as e:
            logger.exception(f"Error appending suggestion: {e}")

    async def get_latest_suggestion(self) -> Optional[str]:
        """Return the latest suggestion block if available."""
        try:
            if not os.path.exists(self.suggestions_path):
                return None

            async with aiofiles.open(self.suggestions_path, "r", encoding="utf-8") as f:
                content = await f.read()

            if not content.strip():
                return None

            lines = content.split("\n")
            last_header_index = -1
            for idx, line in enumerate(lines):
                if line.startswith("=== SUGGESTION @"):
                    last_header_index = idx

            if last_header_index == -1:
                return content.strip()

            suggestion_lines = lines[last_header_index + 1 :]
            suggestion_text = "\n".join(suggestion_lines).strip()
            return suggestion_text or None

        except Exception as e:
            logger.exception(f"Error reading latest suggestion: {e}")
            return None

    async def append_screen_analysis(self, analysis: str) -> None:
        """Append a screen analysis block to the screen analysis file in summaries dir."""
        try:
            if not analysis:
                return

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header = f"\n=== SCREEN ANALYSIS @ {timestamp} ===\n"
            content = header + analysis.strip() + "\n"

            async with aiofiles.open(self.screen_analysis_path, "a", encoding="utf-8") as f:
                await f.write(content)

            logger.info(
                f"Appended screen analysis to {self.screen_analysis_path} ({len(analysis)} chars)"
            )

        except Exception as e:
            logger.exception(f"Error appending screen analysis: {e}")

    async def get_latest_screen_analysis(self) -> Optional[str]:
        """Return the latest screen analysis block if available."""
        try:
            if not os.path.exists(self.screen_analysis_path):
                return None

            async with aiofiles.open(self.screen_analysis_path, "r", encoding="utf-8") as f:
                content = await f.read()

            if not content.strip():
                return None

            lines = content.split("\n")
            last_header_index = -1
            for idx, line in enumerate(lines):
                if line.startswith("=== SCREEN ANALYSIS @"):
                    last_header_index = idx

            if last_header_index == -1:
                return content.strip()

            analysis_lines = lines[last_header_index + 1 :]
            analysis_text = "\n".join(analysis_lines).strip()
            return analysis_text or None

        except Exception as e:
            logger.exception(f"Error reading latest screen analysis: {e}")
            return None

    async def get_current_summary(self) -> Optional[str]:
        """
        Read the current global summary from summary file

        Returns:
            Current summary text or None if file doesn't exist
        """
        try:
            if not os.path.exists(self.summary_path):
                logger.debug("Summary file does not exist yet")
                return None

            async with aiofiles.open(self.summary_path, 'r', encoding='utf-8') as f:
                content = await f.read()

            if not content.strip():
                return None

            summary = self._strip_summary_header(content)
            if summary:
                logger.debug(f"Retrieved current summary ({len(summary)} chars)")
                return summary
            return None

        except Exception as e:
            logger.exception(f"Error reading current summary: {e}")
            return None

    def _format_relative_timestamp(self, seconds: float) -> str:
        """
        Format relative timestamp (seconds from meeting start) to readable format

        Args:
            seconds: Relative timestamp in seconds

        Returns:
            Formatted string like "00:15" or "1:23:45"
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    def get_transcript_path(self) -> str:
        """Get transcript file path"""
        return self.transcript_path

    def get_summary_path(self) -> str:
        """Get summary file path"""
        return self.summary_path

    def get_events_path(self) -> str:
        """Get events file path"""
        return self.events_path

    def _strip_summary_header(self, text: str) -> str:
        """
        Remove storage header metadata from a summary blob if it exists.

        The stored summary files include a standard header block with title,
        last-updated timestamp, and separators. This helper removes those
        lines so the caller receives only the human-written summary content.
        """
        if not text:
            return text

        lines = text.splitlines()
        idx = 0
        while idx < len(lines):
            line = lines[idx].strip()
            if not line:
                idx += 1
                continue
            if line.startswith("=== MEETING SUMMARY"):
                idx += 1
                continue
            if line.startswith("Last Updated:"):
                idx += 1
                continue
            if set(line) == {"="}:
                idx += 1
                continue
            break

        return "\n".join(lines[idx:]).strip()
