from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from fastapi.responses import RedirectResponse
import os
from app.api.recall import add_bot 


router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


class MeetingRequest(BaseModel):
    meeting_url: str
    isTranscript: bool = False
    x_org_name: str
    saveTranscript: bool = True


@router.get("/")
async def bot_html(request: Request, org_name : str):
    return templates.TemplateResponse("bot.html", {"request": request, "org_name" : org_name})


@router.post("/add_scooby")
async def add_scooby_bot(body : MeetingRequest, request: Request):
    meeting_url = body.meeting_url
    is_transcript = body.saveTranscript or body.isTranscript
    bot_id = await add_bot(meeting_url, is_transcript, x_org_name=body.x_org_name)
    return bot_id
