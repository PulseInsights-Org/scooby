import httpx
from fastapi import HTTPException
import os


# 1. Effective error handling
# 2. Bot leaving meeting handling -         handled 
# 3. Other events to be caputred if needed -> Docs.


class RecallBot():
    def __init__(self) -> None:
        pass
    
    async def add_bots(self, meeting_url : str, bot_name : str = "scooby"):
    
        recall_api_url = "https://us-west-2.recall.ai/api/v1/bot/"
        recall_api_key = os.getenv("RECALL_API_KEY")
        if not recall_api_key:
            raise HTTPException(status_code=500, detail="Missing RECALL_API_KEY environment variable")
        
        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "recording_config": {
                "realtime_endpoints": [
                    {
                        "type": "webhook",
                        "url": "https://082aaee79ab3.ngrok-free.app/api/webhook/recall",
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
                        "url": "https://082aaee79ab3.ngrok-free.app/"
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
    
    async def handle_bot_removal(self, bot_id: str) -> dict:

        recall_api_url = f"https://us-west-2.recall.ai/api/v1/bot/{bot_id}/leave_call/"
        recall_api_key = os.getenv("RECALL_API_KEY")
        if not recall_api_key:
            raise HTTPException(status_code=500, detail="Missing RECALL_API_KEY environment variable")

        headers = {
            "Authorization": recall_api_key,
            "accept": "application/json",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    recall_api_url,
                    headers=headers,
                    timeout=30.0,
                )

                if response.status_code in [200, 201]:
                    try:
                        return response.json()
                    except ValueError:
                        # No JSON body returned
                        return {
                            "success": True,
                            "message": f"Successfully removed bot {bot_id} from meeting",
                            "bot_id": bot_id,
                        }
                else:
                    error_detail = response.text
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Failed to remove bot {bot_id} from meeting: {error_detail}",
                    )
        except httpx.TimeoutException:
            raise HTTPException(status_code=408, detail="Request timeout")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    
    async def send_chat_message(self, bot_id: str, message: str, to: str = "everyone", pin: bool = False) -> dict:
        
        recall_api_url = f"https://us-west-2.recall.ai/api/v1/bot/{bot_id}/send_chat_message/"
        recall_api_key = os.getenv("RECALL_API_KEY")
        if not recall_api_key:
            raise HTTPException(status_code=500, detail="Missing RECALL_API_KEY environment variable")

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
    
