import os
import base64
from typing import Optional


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHARES_ROOT = os.path.join(BASE_DIR, "screenshares")


class ScreenshareStorage:

    def __init__(self) -> None:
        self.base_dir = BASE_DIR
        self.root_dir = SCREENSHARES_ROOT

    def _sanitize(self, text: Optional[str]) -> str:
        if not text:
            return "unknown"
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in text)[:64]

    def ensure_meeting_dir(self, org_name: str, bot_id: str) -> str:
        org_safe = self._sanitize(org_name)
        meeting_safe = self._sanitize(bot_id)
        path = os.path.join(self.root_dir, org_safe, meeting_safe)
        os.makedirs(path, exist_ok=True)
        return path

    def save_png_frame(
        self,
        *,
        org_name: str,
        bot_id: str,
        participant_id: str,
        participant_name: Optional[str],
        timestamp_absolute: Optional[str],
        timestamp_relative: Optional[float],
        image_base64: str,
    ) -> str:
        meeting_dir = self.ensure_meeting_dir(org_name, bot_id)

        if timestamp_absolute:
            ts = (
                timestamp_absolute
                .replace(":", "")
                .replace("-", "")
                .replace(".", "_")
                .replace("Z", "z")
            )
        else:
            rel_str = f"{timestamp_relative:.3f}" if timestamp_relative is not None else "0.000"
            ts = f"rel_{rel_str.replace('.', '_')}"

        participant_safe = self._sanitize(participant_name or str(participant_id))
        participant_id_safe = self._sanitize(str(participant_id))

        filename = f"{participant_safe}_{participant_id_safe}_{ts}.png"
        file_path = os.path.join(meeting_dir, filename)

        image_bytes = base64.b64decode(image_base64)
        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return file_path