import os
import base64
from datetime import datetime
from typing import Optional


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # points to app/
SCREENSHARES_DIR = os.path.join(BASE_DIR, "screenshares")


class ScreenshareStorage:
    """Utility for storing screenshare PNG frames on disk.

    Frames are stored under:
        screenshares/<org_name>/<bot_id>/<participant_id>/
    with filenames that include timestamps and participant name for debugging.
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self.base_dir = base_dir or SCREENSHARES_DIR

    def save_png_frame(
        self,
        *,
        org_name: str,
        bot_id: str,
        participant_id: str,
        participant_name: Optional[str],
        timestamp_absolute: Optional[float],
        timestamp_relative: Optional[float],
        image_base64: str,
    ) -> str:
        """Decode a base64 PNG frame and save it to disk.

        Returns the full file path where the frame was stored.
        """
        # Build directory path
        org_safe = org_name or "unknown_org"
        bot_safe = bot_id or "unknown_bot"
        participant_safe = participant_id or "unknown_participant"

        target_dir = os.path.join(
            self.base_dir,
            org_safe,
            bot_safe,
            participant_safe,
        )
        os.makedirs(target_dir, exist_ok=True)

        # Build filename with timestamps
        ts_abs = f"{timestamp_absolute:.3f}" if isinstance(timestamp_absolute, (int, float)) else "na"
        ts_rel = f"{timestamp_relative:.3f}" if isinstance(timestamp_relative, (int, float)) else "na"

        now_str = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
        name_part = (participant_name or "participant").replace(" ", "_")

        filename = f"frame_{name_part}_abs-{ts_abs}_rel-{ts_rel}_{now_str}.png"
        file_path = os.path.join(target_dir, filename)

        # Decode and write PNG bytes
        try:
            png_bytes = base64.b64decode(image_base64)
        except Exception:
            # If decoding fails, still raise so caller can log the issue
            raise

        with open(file_path, "wb") as f:
            f.write(png_bytes)

        return file_path
