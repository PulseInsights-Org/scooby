from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import logging
import os
import json
from datetime import datetime, timezone
from app.api.recall import (
    add_bot,
    get_current_summary_text,
    get_latest_suggestion_text,
    get_latest_screen_analysis_text,
    get_active_bot_id,
    run_vision_screen_analysis_for_active_meeting,
    get_current_meeting_relative_time,
    run_issue_suggestion_for_active_meeting,
    get_current_transcript_relative_time,
)
from app.core.config import get_config
from app.service.cobalt_slack_client import CobaltSlackClient
from app.service.recall_bot import RecallBot

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

rb = RecallBot()
config = get_config()

class MeetingRequest(BaseModel):
    meeting_url: str
    isTranscript: bool = False
    x_org_name: str
    saveTranscript: bool = True

class RemoveBotRequest(BaseModel):
    bot_id: str

class SlackChannelRequest(BaseModel):
    channel_id: str

@router.get("/scooby")
async def bot_html(request: Request):
    return templates.TemplateResponse("bot.html", {"request": request})

@router.get("/")
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


@router.get("/api/bot_status")
async def get_bot_status():
    bot_id = get_active_bot_id()
    return {"bot_id": bot_id, "active": bool(bot_id)}

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


@router.post("/remove_scooby")
async def remove_scooby_bot(body: RemoveBotRequest):
    result = await rb.handle_bot_removal(body.bot_id)
    return result

slack_client = CobaltSlackClient()

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
    """Generate a fresh, time-windowed suggestion and send it to a Slack channel."""

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

    bot_id = get_active_bot_id()
    if not bot_id:
        logger.error(
            "[SUGGEST] No active bot_id available for suggestion. form=%s, query_params=%s",
            dict(form),
            dict(request.query_params),
        )
        return {"status": "error", "error": "no_active_bot"}

    import asyncio

    # Snapshot reference time at request moment to avoid window drift
    T_request = get_current_transcript_relative_time() or get_current_meeting_relative_time()

    async def process_and_send_suggestion(reference_timestamp: float | None = T_request):
        """Background task to generate a RAG-backed suggestion and send it to Slack."""
        try:
            logger.info("[SUGGEST] Starting background suggestion generation for bot_id=%s", bot_id)

            # Send initial "processing" message
            try:
                await slack_client.send_message(
                    channel_id,
                    "processing recent discussion to generate a suggestion...",
                )
            except Exception as e:
                logger.warning("[SUGGEST] Failed to send processing message: %s", e)

            if reference_timestamp is None:
                suggestion_text = (
                    "No transcript timeline is available yet. "
                    "Try discussing the issue for a few seconds, then run /suggest again."
                )
            else:
                suggestion_text = await run_issue_suggestion_for_active_meeting(
                    reference_timestamp=reference_timestamp,
                )

            if not suggestion_text:
                suggestion_text = (
                    "No suggestion could be generated yet. "
                    "Please make sure there is recent discussion about a concrete issue."
                )

            await slack_client.send_message(channel_id, suggestion_text)
            logger.info("[SUGGEST] Successfully sent suggestion to channel_id=%s", channel_id)

        except Exception:
            logger.exception("[SUGGEST] Error in background suggestion task for bot_id=%s", bot_id)
            try:
                await slack_client.send_message(
                    channel_id,
                    "❌ Failed to generate a suggestion. Please try again or check logs for details.",
                )
            except Exception:
                logger.exception("[SUGGEST] Failed to send error message to Slack")

    asyncio.create_task(process_and_send_suggestion())

    logger.info("[SUGGEST] Acknowledged request, suggestion generation in background")
    return {"status": "processing", "message": "Suggestion generation started in background"}


@router.post("/analyze-screen")
async def analyze_screen_from_slack(request: Request):
    """Trigger screenshare analysis for the recent window and send result to Slack.
    
    This endpoint returns immediately to avoid Slack's 3-second timeout,
    then processes the analysis in the background.
    """

    request_received_at = datetime.now(timezone.utc)
    logger.info(
        "[ANALYZE_SCREEN] Incoming request at %s (UTC): query_params=%s",
        request_received_at.isoformat(),
        dict(request.query_params),
    )

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

    # Import asyncio for background task
    import asyncio

    # Snapshot reference time at request moment to avoid window drift
    T_request = get_current_transcript_relative_time() or get_current_meeting_relative_time()

    async def process_and_send_analysis(reference_timestamp: float | None = T_request):
        """Background task to run vision-based screen analysis and send it to Slack.

        Heavy lifting (event selection, Redis frame fetch, Gemini call) is
        delegated to ScreenAnalysisService via recall.run_vision_screen_analysis_for_active_meeting.
        """
        try:
            logger.info(
                "[ANALYZE_SCREEN] Starting background analysis for bot_id=%s, channel_id=%s, request_received_at=%s (UTC), reference_timestamp=%s",
                bot_id,
                channel_id,
                request_received_at.isoformat(),
                reference_timestamp,
            )

            # Send initial "processing" message
            try:
                await slack_client.send_message(
                    channel_id,
                    "processing recent screenshare frames...",
                )
            except Exception as e:
                logger.warning("[ANALYZE_SCREEN] Failed to send processing message: %s", e)

            if reference_timestamp is None:
                analysis_text = (
                    "No transcript or screenshare timeline is available yet. "
                    "Try speaking about the issue and sharing your screen, then run /capture again."
                )
            else:
                analysis_text = await run_vision_screen_analysis_for_active_meeting(
                    reference_timestamp=reference_timestamp,
                )

            if not analysis_text:
                analysis_text = (
                    "No screenshare analysis is available yet. "
                    "Please make sure the meeting has screenshare-related events and frames."
                )

            # Send the actual analysis result
            await slack_client.send_message(channel_id, analysis_text)
            logger.info("[ANALYZE_SCREEN] Successfully sent vision-based analysis to channel_id=%s", channel_id)
            
        except Exception:
            logger.exception("[ANALYZE_SCREEN] Error in background analysis task for bot_id=%s", bot_id)
            try:
                await slack_client.send_message(
                    channel_id,
                    "❌ Failed to analyze screenshare frames. Please try again or check logs for details."
                )
            except Exception:
                logger.exception("[ANALYZE_SCREEN] Failed to send error message to Slack")

    # Start background task
    asyncio.create_task(process_and_send_analysis())
    
    # Return immediately to avoid Slack timeout
    logger.info("[ANALYZE_SCREEN] Acknowledged request, processing in background")
    return {"status": "processing", "message": "Analysis started in background"}



