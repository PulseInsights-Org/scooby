from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import logging
import os
import json
from app.api.recall import add_bot, get_current_summary_text, get_latest_suggestion_text, get_active_bot_id
from app.core.config import get_config
from app.service.cobalt_slack_client import CobaltSlackClient
from app.service.screen_analysis_service import ScreenAnalysisService

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

class MeetingRequest(BaseModel):
    meeting_url: str
    isTranscript: bool = False
    x_org_name: str
    saveTranscript: bool = True

class SlackChannelRequest(BaseModel):
    channel_id: str

@router.get("/")
async def bot_html(request: Request):
    return templates.TemplateResponse("bot.html", {"request": request})

@router.get("/dashboard")
async def dashboard_html(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

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

slack_client = CobaltSlackClient()
screen_analysis_service = ScreenAnalysisService()

@router.post("/summary")
async def send_summary_to_slack(request: Request):
    """Send the latest meeting summary to a Slack channel."""

    logger.info("[SUMMARY] Incoming request: query_params=%s", dict(request.query_params))

    form = await request.form()
    channel_id = (
        form.get("channel_id")
        or form.get("channelId")
        or form.get("channel")
    )

    if not channel_id:
        qp = request.query_params
        channel_id = (
            qp.get("channel_id")
            or qp.get("channelId")
            or qp.get("channel")
        )

    if not channel_id:
        logger.error("[SUMMARY] Missing channel_id in request. query_params=%s", dict(request.query_params))
        return {"status": "error", "error": "missing_channel_id"}

    summary = await get_current_summary_text()
    if not summary:
        logger.warning("[SUMMARY] No summary available for channel_id=%s", channel_id)
        return {"status": "no_summary_available"}

    try:
        await slack_client.send_message(channel_id, summary)
        logger.info("[SUMMARY] Sent summary to channel_id=%s", channel_id)
    except Exception:
        logger.exception("[SUMMARY] Failed to send summary to Slack for channel_id=%s", channel_id)
        return {"status": "error", "error": "slack_send_failed"}

    return {"status": "sent", "type": "summary"}

@router.post("/suggest")
async def send_suggestion_to_slack(request: Request):
    """Send the latest suggestion to a Slack channel."""

    logger.info("[SUGGEST] Incoming request: query_params=%s", dict(request.query_params))

    form = await request.form()
    channel_id = (
        form.get("channel_id")
        or form.get("channelId")
        or form.get("channel")
    )

    if not channel_id:
        qp = request.query_params
        channel_id = (
            qp.get("channel_id")
            or qp.get("channelId")
            or qp.get("channel")
        )

    if not channel_id:
        logger.error("[SUGGEST] Missing channel_id in request. query_params=%s", dict(request.query_params))
        return {"status": "error", "error": "missing_channel_id"}

    suggestion = await get_latest_suggestion_text()
    if not suggestion:
        logger.warning("[SUGGEST] No suggestion available for channel_id=%s", channel_id)
        return {"status": "no_suggestion_available"}

    try:
        await slack_client.send_message(channel_id, suggestion)
        logger.info("[SUGGEST] Sent suggestion to channel_id=%s", channel_id)
    except Exception:
        logger.exception("[SUGGEST] Failed to send suggestion to Slack for channel_id=%s", channel_id)
        return {"status": "error", "error": "slack_send_failed"}

    return {"status": "sent", "type": "suggestion"}


@router.post("/analyze-screen")
async def analyze_screen_from_slack(request: Request):
    """Trigger screenshare analysis for the recent window and send result to Slack."""

    logger.info("[ANALYZE_SCREEN] Incoming request: query_params=%s", dict(request.query_params))

    form = await request.form()

    channel_id = (
        form.get("channel_id")
        or form.get("channelId")
        or form.get("channel")
    )

    bot_id = get_active_bot_id()

    if not channel_id:
        qp = request.query_params
        channel_id = (
            qp.get("channel_id")
            or qp.get("channelId")
            or qp.get("channel")
        )

    if not channel_id:
        logger.error("[ANALYZE_SCREEN] Missing channel_id in request. query_params=%s", dict(request.query_params))
        return {"status": "error", "error": "missing_channel_id"}

    if not bot_id:
        logger.error(
            "[ANALYZE_SCREEN] No active bot_id available for analysis. form=%s, query_params=%s",
            dict(form),
            dict(request.query_params),
        )
        return {"status": "error", "error": "no_active_bot"}

    try:
        analysis_text = await screen_analysis_service.analyze_recent_screens(bot_id=bot_id)
    except Exception:
        logger.exception("[ANALYZE_SCREEN] Error while analyzing recent screens for bot_id=%s", bot_id)
        return {"status": "error", "error": "analysis_failed"}

    try:
        await slack_client.send_message(channel_id, analysis_text)
        logger.info("[ANALYZE_SCREEN] Sent analysis to channel_id=%s", channel_id)
    except Exception:
        logger.exception("[ANALYZE_SCREEN] Failed to send analysis to Slack for channel_id=%s", channel_id)
        return {"status": "error", "error": "slack_send_failed"}

    return {"status": "sent", "type": "screen_analysis"}

