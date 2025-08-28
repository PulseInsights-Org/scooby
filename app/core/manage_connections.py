from fastapi import WebSocket
from typing import Dict
import logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}

    def add_connection(self, org_name: str, connection_id: str, websocket: WebSocket):
        if org_name not in self.active_connections:
            self.active_connections[org_name] = {}
        self.active_connections[org_name][connection_id] = websocket
        logger.info(f"Added WebSocket {connection_id} for tenant {org_name}. "
                    f"Tenant connections: {len(self.active_connections[org_name])}")

    def remove_connection(self, org_name: str, connection_id: str):
        if org_name in self.active_connections and connection_id in self.active_connections[org_name]:
            del self.active_connections[org_name][connection_id]
            logger.info(f"Removed WebSocket {connection_id} for tenant {org_name}. "
                        f"Tenant connections left: {len(self.active_connections[org_name])}")
            if not self.active_connections[org_name]:
                del self.active_connections[org_name] 

    async def send_to_tenant(self, org_name: str, message: dict):
        """Send a message only to all connections of one tenant"""
        if org_name not in self.active_connections:
            return

        disconnected = []
        for connection_id, websocket in self.active_connections[org_name].items():
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.exception(f"Error sending to WebSocket {connection_id}: {e}")
                disconnected.append(connection_id)

        for conn_id in disconnected:
            self.remove_connection(org_name, conn_id)
