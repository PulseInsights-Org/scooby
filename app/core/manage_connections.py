from fastapi import WebSocket
from typing import Dict


# tenant wise connection management -> using org-id + tenent_id


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    def add_connection(self, connection_id: str, websocket: WebSocket):
        self.active_connections[connection_id] = websocket
        print(f"Added WebSocket connection {connection_id}. Total active: {len(self.active_connections)}")
    
    def remove_connection(self, connection_id: str):
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
            print(f"Removed WebSocket connection {connection_id}. Total active: {len(self.active_connections)}")
    
    async def send_to_all(self, message: dict):
        if not self.active_connections:
            return
            
        disconnected = []
        for connection_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(message)
            except Exception as e:
                print(f"Error sending to WebSocket {connection_id}: {e}")
                disconnected.append(connection_id)
        
        for connection_id in disconnected:
            self.remove_connection(connection_id)