from typing import Dict, List, Optional
import logging
import json

logger = logging.getLogger(__name__)


class ParticipantsManager:
    """
    Manages participants state and optionally keeps an external model's
    participants field synchronized.
    """

    def __init__(self, org_name: str = None, connection_manager=None):
        self._list: List[Dict] = []
        self.org_name = org_name

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
            
            action = "updated" if existing else "joined"
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
            logger.info(f"Participant left: {p['name']}")
            
    
    
    def get_active_participants(self) -> List[Dict]:
        """Get only participants who are currently joined."""
        return [p for p in self._list if p["status"] == "joined"]
    
    def get_participant_count(self) -> int:
        """Get count of active participants."""
        return len(self.get_active_participants())
    
    def get_current_participants(self) -> List[Dict]:
        """Gets all participants who are currently in the meeting (status == 'joined').
        This function is designed to be used as a tool call in Gemini Live."""
        return self.get_active_participants()
    
    def get_all_joined_participants(self) -> List[Dict]:
        """Gets all participants who have joined the meeting, including those who later left.
        This function is designed to be used as a tool call in Gemini Live."""
        return self._list.copy()
            
