from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import os
from app.api.recall import add_bot 


router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class MeetingRequest(BaseModel):
    meeting_url: str
    isTranscript: bool = False


@router.get("/")
async def bot_html(request: Request):
    return templates.TemplateResponse("bot.html", {"request": request})


@router.post("/add_scooby")
async def add_scooby_bot(body : MeetingRequest, request: Request):
    meeting_url = body.meeting_url
    is_transcript = body.isTranscript
    bot_id = await add_bot(meeting_url, is_transcript)
    if not bot_id:
        return {
            "message": "Scooby Bot already exists, Please remove and try again"
        }
    return {"bot_id": bot_id}
