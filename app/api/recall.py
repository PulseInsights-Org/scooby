from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
import os
import logging
from app.service.recall_bot import RecallBot
from app.core.manage_connections import ConnectionManager
from app.service.gemini_live import GeminiLive
from app.service.participants import ParticipantsManager
from app.core.utils import TranscriptWriter, BotContext, InactivityMonitor
from app.service.transcript_ingestion import TranscriptIngestion

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")

cm = ConnectionManager()
rb = RecallBot()
participants_manager = ParticipantsManager()
bot_context = BotContext()

model = GeminiLive(connection_manager=cm)

current_bot_id = None
current_meeting_url = None
transcripts_enabled = False
current_x_org_id = None
current_tenant_id = None

transcript_writer = TranscriptWriter(
    enabled_getter=lambda: transcripts_enabled,
    transcripts_dir=TRANSCRIPTS_DIR,
    meeting_url_getter=lambda: current_meeting_url,
)

# Transcript ingestion client instance used during bot end states
ti = TranscriptIngestion(org_id="")

def _set_inactive():
    global current_bot_id, current_meeting_url, transcripts_enabled, current_x_org_id, current_tenant_id
    current_bot_id = None
    current_meeting_url = None
    transcripts_enabled = False
    current_x_org_id = None
    current_tenant_id = None
    try:
        bot_context.clear()
        BotContext.remove_model_context(model)
    except Exception:
        pass

# Inactivity monitor instance
inactivity_monitor = InactivityMonitor(
    get_current_bot_id=lambda: current_bot_id,
    participants_manager=participants_manager,
    model=model,
    transcript_writer=transcript_writer,
    bot_name="scooby",
    remove_bot=rb.handle_bot_removal,
    on_cleared=lambda: (_set_inactive(), bot_context.print_active_bot()),
)

async def add_bot(meeting_url: str, is_transcript: bool = False, *, x_org_id: str, tenant_id: str) -> str | None:
    """Create a Recall bot and update local module state."""
    global current_bot_id, current_meeting_url, transcripts_enabled, current_x_org_id, current_tenant_id
    # Enforce single active bot at a time
    if current_bot_id is not None:
        # A bot is already active; do not create another
        return None
    bot_id = await rb.add_bots(meeting_url)
    if bot_id:
        current_bot_id = bot_id
        current_meeting_url = meeting_url
        transcripts_enabled = is_transcript
        current_x_org_id = x_org_id
        current_tenant_id = tenant_id
        try:
            bot_context.bot_id = bot_id
            bot_context.meeting_url = meeting_url
            bot_context.transcripts_enabled = is_transcript
        except Exception:
            pass
        participants_manager.reset()
        try:
            model.participants = list(participants_manager.list)
        except Exception:
            pass
        try:
            model.bot_id = bot_id
        except Exception:
            pass
        bot_context.print_active_bot()
        # Initialize inactivity tracking and start watcher
        inactivity_monitor.start(bot_id)
    return bot_id


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connection_id = f"ws_{id(websocket)}"
    cm.add_connection(connection_id, websocket)

    try:
        await websocket.send_json({
            "type": "status",
            "connected": True,
            "bot_type": "scooby"
        })

        while True:
            _ = await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info(f"WebSocket {connection_id} disconnected")
        cm.remove_connection(connection_id)
    except Exception as e:
        logger.exception(f"WebSocket error for {connection_id}: {e}")
        cm.remove_connection(connection_id)


@router.post("/api/webhook/recall/bot-status")
async def recall_bot_status_webhook(request: Request):
    logger.info("Received BOT STATUS webhook from Recall.ai")
    try:
        payload = await request.json()
        logger.debug(f"Bot Status Payload: {payload}")
        event_type = payload.get("type")
        data = payload.get("data", {})

        if event_type == "bot.status_change":
            bot_id = data.get("id")
            status = data.get("status")
            sub_code = data.get("sub_code")

            logger.info(f"Bot {bot_id} status changed to: {status}")
            if sub_code:
                logger.info(f"Sub code: {sub_code}")

            if current_bot_id and bot_id != current_bot_id:
                logger.debug(f"Ignoring status for non-current bot {bot_id}")
                return {"status": "ok"}

            if status == "joining_call":
                logger.info(f"Bot {bot_id} is joining the meeting")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] is joining the meeting")

            elif status == "in_call":
                logger.info(f"Bot {bot_id} successfully joined the meeting")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] joined the meeting")

            elif status == "in_call_recording":
                logger.info(f"Bot {bot_id} is now recording")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] started recording")

            elif status == "call_ended":
                logger.info(f"Bot {bot_id} call ended")
                transcript_writer.save_line(bot_id, "BOT_STATUS", "Call ended")
                try:
                    await BotContext.ingest_and_cleanup_transcript(
                        bot_id,
                        transcripts_enabled=transcripts_enabled,
                        transcripts_dir=TRANSCRIPTS_DIR,
                        meeting_url=current_meeting_url,
                        ti=ti,
                        x_org_id=current_x_org_id,
                        tenant_id=current_tenant_id,
                        logger=logger,
                    )
                    participants_manager.reset()
                    try:
                        model.participants = []
                    except Exception:
                        pass
                    # stop inactivity monitor
                    try:
                        inactivity_monitor.stop()
                    except Exception:
                        pass
                    _set_inactive()
                except Exception:
                    logger.exception("Error while handling call_ended cleanup")
                bot_context.print_active_bot()

            elif status == "done":
                logger.info(f"Bot {bot_id} finished successfully")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] finished successfully")
                try:
                    await BotContext.ingest_and_cleanup_transcript(
                        bot_id,
                        transcripts_enabled=transcripts_enabled,
                        transcripts_dir=TRANSCRIPTS_DIR,
                        meeting_url=current_meeting_url,
                        ti=ti,
                        x_org_id=current_x_org_id,
                        tenant_id=current_tenant_id,
                        logger=logger,
                    )
                    participants_manager.reset()
                    try:
                        model.participants = []
                    except Exception:
                        pass
                    _set_inactive()
                    try:
                        inactivity_monitor.stop()
                    except Exception:
                        pass
                except Exception:
                    logger.exception("Error while handling done cleanup")
                bot_context.print_active_bot()

            elif status == "fatal":
                logger.error(f"Bot {bot_id} encountered a fatal error")
                if sub_code:
                    logger.error(f"Fatal error reason: {sub_code}")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot fatal error: {sub_code or 'unknown reason'}")
                try:
                    await BotContext.ingest_and_cleanup_transcript(
                        bot_id,
                        transcripts_enabled=transcripts_enabled,
                        transcripts_dir=TRANSCRIPTS_DIR,
                        meeting_url=current_meeting_url,
                        ti=ti,
                        x_org_id=current_x_org_id,
                        tenant_id=current_tenant_id,
                        logger=logger,
                    )
                    participants_manager.reset()
                    try:
                        model.participants = []
                    except Exception:
                        pass
                    _set_inactive()
                    try:
                        inactivity_monitor.stop()
                    except Exception:
                        pass
                except Exception:
                    logger.exception("Error while handling fatal cleanup")
                bot_context.print_active_bot()

            else:
                logger.warning(f"Unhandled bot status: {status}")

        else:
            logger.warning(f"Unhandled bot status event type: {event_type}")

    except Exception as e:
        logger.exception(f"Error processing bot status webhook: {e}")

    return {"status": "ok"}


@router.post("/api/webhook/recall")
async def recall_webhook(request: Request):
    logger.info("Received REALTIME webhook from Recall.ai")
    try:
        payload = await request.json()
        logger.debug(f"Realtime Payload: {payload}")

        event_type = payload.get("event")
        data = payload.get("data", {})
        bot_info = data.get("bot", {})
        bot_id = bot_info.get("id")

        if current_bot_id is None:
            logger.debug("No current bot set; ignoring realtime event")
            return {"status": "ok"}

        if current_bot_id and bot_id != current_bot_id:
            logger.debug(f"Ignoring realtime event for non-current bot {bot_id}")
            return {"status": "ok"}

        if event_type == "transcript.data":
            inactivity_monitor.record_activity()
            inactivity_monitor.record_transcript()
            words = payload["data"]["data"]["words"]
            speaker = payload["data"]["data"]["participant"]["name"]
            spoken_text = " ".join([w["text"] for w in words])
            logger.info(f"Transcribed text from {speaker}: {spoken_text}")
            transcript_writer.save_line(bot_id, speaker, spoken_text)

            if "scooby" in spoken_text.lower():
                logger.info(f"Scooby mentioned by {speaker}: {spoken_text}")
                try:
                    logger.debug(f"Sending to Gemini: {spoken_text}")
                    await model.connect_to_gemini(text=spoken_text)
                    logger.debug("Sent to Gemini successfully")
                except Exception as e:
                    logger.exception(f"Error sending to Gemini: {e}")

            else:
                model.chat_history.append(
                    {"role": "user", "content": spoken_text.strip(), "type": "audio_response"}
                )

        elif event_type == "participant_events.join":
            inactivity_monitor.record_activity()
            participant_data = payload["data"]["data"]["participant"]
            action = payload["data"]["data"]["action"]

            if action == "join":
                participants_manager.add(participant_data)
                try:
                    model.participants = list(participants_manager.list)
                except Exception:
                    pass
                logger.info(f"Total participants: {len(participants_manager.list)}")
                bot_context.print_active_bot()
                transcript_writer.save_line(
                    bot_id,
                    "INFO : PARTICIPANT",
                    f"JOINED : {participant_data.get('name')} ({participant_data.get('id')})"
                )

        elif event_type == "participant_events.leave":
            inactivity_monitor.record_activity()
            participant_data = payload["data"]["data"]["participant"]
            participant_id = participant_data["id"]
            participant_name = participant_data["name"]

            if participant_name.lower() != "scooby":
                participants_manager.mark_left(participant_id)
                try:
                    model.participants = list(participants_manager.list)
                except Exception:
                    pass
                p = participants_manager.get(participant_id)
                if p:
                    logger.info(f"Participant left: {p['name']}")
            transcript_writer.save_line(
                bot_id,
                "INFO : PARTICIPANT",
                f"LEFT: {participant_name} ({participant_id})"
            )
            bot_context.print_active_bot()

        else:
            logger.warning(f"Unhandled realtime event: {event_type}")

    except Exception as e:
        logger.exception(f"Error processing realtime webhook: {e}")

    return {"status": "ok"}
