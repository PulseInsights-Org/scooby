from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class ParticipantsManager:
    """
    Manages participants state and optionally keeps an external model's
    participants field synchronized.
    """

    def __init__(self):
        self._list: List[Dict] = []

    @property
    def list(self) -> List[Dict]:
        return self._list

    def reset(self) -> None:
        self._list.clear()
        

    def add(self, data: Dict) -> None:
        try:
            participant_id = data.get("id")
            participant_name = data.get("name")
            if not participant_id or not participant_name:
                logger.warning(f"Invalid participant data: {data}")
                return

            existing = next((p for p in self._list if p["id"] == participant_id), None)
            payload = {
                "id": participant_id,
                "name": participant_name,
                "is_host": data.get("is_host", False),
                "platform": data.get("platform", "unknown"),
                "extra_data": data.get("extra_data", {}),
                "status": "joined",
            }
            if existing is None:
                self._list.append(payload)
                logger.info(f"Added participant: {participant_name}")
            else:
                existing.update(payload)
                logger.info(f"Updated participant: {participant_name}")
        finally:
            pass

    def get(self, participant_id: str) -> Optional[Dict]:
        try:
            return next((p for p in self._list if p["id"] == participant_id), None)
        except Exception as e:
            logger.exception(f"Error getting participant: {e}")
            return None

    def mark_left(self, participant_id: str) -> None:
        p = self.get(participant_id)
        if p:
            p["status"] = "left"
            
