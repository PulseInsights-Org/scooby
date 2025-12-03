from fastapi import WebSocket
from typing import Dict
import logging

logger = logging.getLogger(__name__)

# tenant wise connection management -> using org-id + tenent_id

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    def add_connection(self, connection_id: str, websocket: WebSocket):
        self.active_connections[connection_id] = websocket
        logger.info(f"Added WebSocket connection {connection_id}. Total active: {len(self.active_connections)}")
    
    def remove_connection(self, connection_id: str):
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
            logger.info(f"Removed WebSocket connection {connection_id}. Total active: {len(self.active_connections)}")
    
    async def send_to_all(self, message: dict):
        """Send message to all connected WebSocket clients"""
        if not self.active_connections:
            return

        # Filter out audio messages (no longer needed after Gemini Live removal)
        if message.get("type") == "audio":
            logger.debug("Skipping audio message (Gemini Live removed)")
            return

        disconnected = []
        for connection_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.exception(f"Error sending to WebSocket {connection_id}: {e}")
                disconnected.append(connection_id)

        for connection_id in disconnected:
            self.remove_connection(connection_id)