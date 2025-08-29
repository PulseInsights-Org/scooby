from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from fastapi.responses import RedirectResponse
import os
from app.api.recall import add_bot
from app.core.utils import BotContext


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
    # Check if organization already has an active bot
    if BotContext.has_active_bot_for_org(body.x_org_name):
        active_bot = BotContext.get_active_bot_for_org(body.x_org_name)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Active bot already exists",
                "message": f"There is already an active Scooby bot for organization '{body.x_org_name}' running in a meeting.",
                "org_name": body.x_org_name,
                "active_bot_id": active_bot.bot_id if active_bot else None
            }
        )
    
    meeting_url = body.meeting_url
    is_transcript = body.saveTranscript or body.isTranscript
    bot_id = await add_bot(meeting_url, is_transcript, x_org_name=body.x_org_name)
    return {"bot_id": bot_id, "org_name": body.x_org_name, "status": "created"}
