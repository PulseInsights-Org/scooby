from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
import logging
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class TranscriptItem:
    """Single transcript item with metadata"""
    speaker: str
    text: str
    timestamp: datetime
    start_time: float  # Relative timestamp from Recall.ai
    end_time: float

    def to_text(self, include_timestamp: bool = True) -> str:
        """Format as readable text"""
        if include_timestamp:
            time_str = self.timestamp.strftime("%H:%M:%S")
            return f"[{time_str}] {self.speaker}: {self.text}"
        return f"{self.speaker}: {self.text}"


class TranscriptBuffer:
    """
    Manages buffering of transcript items with dual trigger logic:
    - Item count threshold (5-7 items)
    - Time threshold (15 seconds since first item)
    """

    def __init__(self, max_items: int = 7, max_seconds: float = 15.0):
        self.max_items = max_items
        self.max_seconds = max_seconds
        self._buffer: deque[TranscriptItem] = deque(maxlen=max_items * 2)  # Extra capacity
        self._first_item_time: Optional[datetime] = None

    def add(self, speaker: str, text: str, start_time: float, end_time: float) -> None:
        """Add transcript item to buffer"""
        item = TranscriptItem(
            speaker=speaker,
            text=text,
            timestamp=datetime.now(timezone.utc),
            start_time=start_time,
            end_time=end_time
        )

        if len(self._buffer) == 0:
            self._first_item_time = item.timestamp

        self._buffer.append(item)
        logger.debug(f"Added to buffer: {speaker} ({len(self._buffer)} items)")

    def should_flush(self) -> bool:
        """Check if buffer should be flushed based on count or time"""
        if len(self._buffer) == 0:
            return False

        # Check item count threshold
        if len(self._buffer) >= self.max_items:
            logger.info(f"Buffer flush triggered: item count ({len(self._buffer)} >= {self.max_items})")
            return True

        # Check time threshold
        if self._first_item_time:
            elapsed = (datetime.now(timezone.utc) - self._first_item_time).total_seconds()
            if elapsed >= self.max_seconds:
                logger.info(f"Buffer flush triggered: time elapsed ({elapsed:.1f}s >= {self.max_seconds}s)")
                return True

        return False

    def flush(self) -> List[TranscriptItem]:
        """Get all items and clear buffer"""
        items = list(self._buffer)
        self._buffer.clear()
        self._first_item_time = None
        logger.info(f"Flushed {len(items)} items from buffer")
        return items

    def peek(self) -> List[TranscriptItem]:
        """View buffer without clearing"""
        return list(self._buffer)

    def size(self) -> int:
        """Current buffer size"""
        return len(self._buffer)

    def is_empty(self) -> bool:
        """Check if buffer is empty"""
        return len(self._buffer) == 0
