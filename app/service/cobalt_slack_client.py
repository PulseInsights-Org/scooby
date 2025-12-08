import httpx
from app.core.config import get_config


class CobaltSlackClient:
    """Client for sending messages to Slack via GoCobalt workflow."""

    def __init__(
        self,
        *,
        base_url: str = "https://api.gocobalt.io",
        workflow_path: str = "/api/v1/workflow/6933fb124a2dff8e2df2c6b2/execute",
        linked_account_id: str = "Nexus-Chat",
        slug: str = "slack",
        sync_execution: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.workflow_path = workflow_path

        config = get_config()
        self.api_key = config.cobalt_api_key
        self.linked_account_id = linked_account_id
        self.slug = slug
        self.sync_execution = sync_execution

    async def send_message(self, channel_id: str, message: str) -> dict:
        """Send a message to the given Slack channel via GoCobalt workflow."""
        url = f"{self.base_url}{self.workflow_path}"

        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key or "",
            "linked_account_id": self.linked_account_id,
            "slug": self.slug,
            "sync_execution": "true" if self.sync_execution else "false",
        }

        payload = {
            "channel_id": channel_id,
            "message": message,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)
            response.raise_for_status()
            return response.json()
