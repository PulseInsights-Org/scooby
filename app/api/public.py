from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import os
from app.api.recall import add_bot 
from app.core.config import get_config


router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class MeetingRequest(BaseModel):
    meeting_url: str
    isTranscript: bool = False
    x_org_name: str
    saveTranscript: bool = True


@router.get("/")
async def bot_html(request: Request):
    return templates.TemplateResponse("bot.html", {"request": request})


@router.get("/api/config")
async def get_frontend_config():
    """Serve frontend configuration"""
    config = get_config()
    
    # Get public base URL and convert to WebSocket URL
    public_base_url = config.public_base_url
    if not public_base_url:
        # Fallback to localhost for development
        public_base_url = "http://localhost:8000"
    
    # Convert https:// to wss:// for WebSocket URL
    ws_base_url = public_base_url.replace('https://', 'wss://').replace('http://', 'ws://')
    
    return {
        "wsUrl": f"{ws_base_url}/ws",
        "publicBaseUrl": public_base_url
    }


@router.post("/add_scooby")
async def add_scooby_bot(body : MeetingRequest, request: Request):
    meeting_url = body.meeting_url
    is_transcript = body.saveTranscript or body.isTranscript
    bot_id = await add_bot(meeting_url, is_transcript, x_org_name=body.x_org_name)
    if not bot_id:
        return {
            "message": "Scooby Bot already exists, Please remove and try again"
        }
    return {"bot_id": bot_id}

