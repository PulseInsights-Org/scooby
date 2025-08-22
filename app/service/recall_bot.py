import httpx
from fastapi import HTTPException


# 1. Effective error handling
# 2. Bot leaving meeting handling
# 3. Other events to be caputred if needed -> Docs.


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
                        "url": "https://9ea1e96036c1.ngrok-free.app/api/webhook/recall",
                        "events": ["transcript.data","participant_events.join"]
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
                        "url": "https://9ea1e96036c1.ngrok-free.app/"
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
    
    def handle_bot_removal(self):
        pass