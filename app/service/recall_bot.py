import httpx
from fastapi import HTTPException


class RecallBot():
    def __init__(self) -> None:
        pass
    
    async def add_bots(self, meeting_url : str, bot_name : str = "scooby"):
    
        recall_api_url = "https://us-west-2.recall.ai/api/v1/bot/"
        recall_api_key = "8487c64e0ef42223efb24178c870d178c2c494f5"
        
        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "recording_config": {
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": "https://95b3eb3c1f62.ngrok-free.app/api/webhook/recall",
                        "events": [
                            "transcript.data",
                            "participant_events.join",
                            "participant_events.leave",
                        ]
                    }
                ],
                "transcript": {
                    "provider": {
                        "meeting_captions": {}
                    }
                }
            },
            "output_media": {
                "camera": { 
                    "kind": "webpage",
                    "config": {
                        "url": "https://95b3eb3c1f62.ngrok-free.app/"
                    }
                }
            },
            "variant": {
                "zoom": "web_4_core",
                "google_meet": "web_4_core",
                "microsoft_teams": "web_4_core"
            }
        }
        
        headers = {
            "Authorization": recall_api_key,
            "accept": "application/json",
            "content-type": "application/json"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    recall_api_url,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
                
                if response.status_code in [200, 201]:
                    bot_data = response.json()
                    bot_id = bot_data.get("id")
                    return bot_id
                    
                else:
                    error_detail = response.text
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Failed to add {bot_name} AI bot to meeting: {error_detail}"
                    )
                    
        except httpx.TimeoutException:
            raise HTTPException(status_code=408, detail="Request timeout")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    
    async def send_chat_message(self, bot_id: str, message: str, to: str = "everyone", pin: bool = False) -> dict:
        """Send a chat message to a meeting via Recall bot.
        Mirrors the style and error handling of add_bots().

        Args:
            bot_id: The Recall bot ID.
            message: The message text to send.
            to: Recipient scope (e.g., "everyone").
            pin: Whether to pin the message in the meeting UI.

        Returns:
            Parsed JSON response from Recall API on success.
        """
        
        recall_api_url = f"https://us-west-2.recall.ai/api/v1/bot/{bot_id}/send_chat_message/"
        recall_api_key = "8487c64e0ef42223efb24178c870d178c2c494f5"

        payload = {
            "to": to,
            "message": message,
            "pin": pin,
        }

        headers = {
            "Authorization": recall_api_key,
            "accept": "application/json",
            "content-type": "application/json",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    recall_api_url,
                    json=payload,
                    headers=headers,
                    timeout=30.0,
                )

                if response.status_code in [200, 201]:
                    return response.json()
                else:
                    error_detail = response.text
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Failed to send chat message via bot {bot_id}: {error_detail}",
                    )
        except httpx.TimeoutException:
            raise HTTPException(status_code=408, detail="Request timeout")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    
    
    