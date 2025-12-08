import httpx
import logging
from typing import Optional
from app.core.config import get_config

logger = logging.getLogger(__name__)

class SlackNotifier:
    def __init__(self):
        self.config = get_config()
        self.api_key = self.config.slack_api_key
        self.base_url = "https://api.gocobalt.io/api/v1/workflow/6933fb124a2dff8e2df2c6b2/execute"
        self.default_channel = "C0A1N77BECU"  # Default channel, can be overridden per message

    async def send_message(
        self,
        message: str,
        channel_id: Optional[str] = None,
        thread_ts: Optional[str] = None
    ) -> bool:
        """
        Send a message to Slack via the Cobalt API
        
        Args:
            message: The message to send
            channel_id: Optional Slack channel ID (defaults to the one from config)
            thread_ts: Optional thread timestamp to reply in a thread
            
        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        if not self.api_key:
            logger.warning("Slack API key not configured")
            return False

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "linked_account_id": "Nexus-Chat",
            "slug": "slack",
            "sync_execution": "true"
        }

        payload = {
            "channel_id": channel_id or self.default_channel,
            "message": message
        }

        if thread_ts:
            payload["thread_ts"] = thread_ts

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                    timeout=10.0
                )
                response.raise_for_status()
                logger.info(f"Message sent to Slack: {message[:100]}...")
                return True
                
        except Exception as e:
            logger.error(f"Failed to send Slack message: {str(e)}")
            return False

# Global instance for easy importing
slack_notifier = SlackNotifier()
