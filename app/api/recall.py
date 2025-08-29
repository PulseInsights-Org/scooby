from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
import os
import logging
from app.service.recall_bot import RecallBot
from app.core.manage_connections import ConnectionManager
from app.service.gemini_live import GeminiLive
from app.service.participants import ParticipantsManager
from app.core.utils import TranscriptWriter, BotContext, InactivityMonitor
from app.service.transcript_ingestion import TranscriptIngestion
from app.core.manage_tenants import TenantManager , TenantRegistry

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")

cm = ConnectionManager()
rb = RecallBot()
registry = TenantRegistry()


ti = TranscriptIngestion(org_name="")

async def add_bot(meeting_url: str, is_transcript: bool = False, *, x_org_name: str) -> str | None:
    """Create a Recall bot and update local module state."""
    
    bot_id = await rb.add_bots(meeting_url=meeting_url, org_name=x_org_name)
    if bot_id:
        model1 = GeminiLive(connection_manager=cm)
        tm1 = TenantManager(bot_id=bot_id,
                            org_name=x_org_name,
                            processed_audio=None,
                            meeting_url = meeting_url,
                            is_transcript = is_transcript,
                            model = model1,
                            recall = rb)
        
        registry.add_manager(bot_id=bot_id, manager=tm1)
    return bot_id


@router.websocket("/ws/{org_name}")
async def websocket_endpoint(websocket: WebSocket, org_name : str):
    await websocket.accept()
    connection_id = f"ws_{id(websocket)}"
    cm.add_connection(org_name, connection_id, websocket)

    try:
        await websocket.send_json({
            "type": "status",
            "connected": True,
            "bot_type": "scooby",
            "org_name" : org_name,
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
        # Some Recall deliveries may set `event` instead of `type`
        event_type = (payload.get("type") or payload.get("event") or "").strip() or None
        data = payload.get("data", {}) or {}
        if not event_type:
            # Log full payload at INFO to aid debugging when schema varies
            logger.info(f"Bot Status Payload (no event/type): {payload}")

        # Accept common variants and explicit bot.* events
        normalized_event = (event_type or "").lower() if event_type else None
        is_status_event = normalized_event in {"bot.status_change", "status_change", "bot.status"} or ("status" in data or "status" in payload)

        # Map explicit bot.* events to a synthetic status when Recall sends them
        mapped_status = None
        if normalized_event and normalized_event.startswith("bot."):
            status_map = {
                "bot.joining_call": "joining_call",
                "bot.in_call": "in_call",
                "bot.in_call_not_recording": "in_call",
                "bot.in_call_recording": "in_call_recording",
                "bot.call_ended": "call_ended",
                "bot.done": "done",
                "bot.fatal": "fatal",
            }
            mapped_status = status_map.get(normalized_event)
            if mapped_status:
                is_status_event = True

        if is_status_event:
            # Extract fields from multiple possible locations
            inner_data = (data.get("data", {}) or {})
            bot_id = (
                (data.get("bot", {}) or {}).get("id")
                or inner_data.get("bot_id")
                or (inner_data.get("bot", {}) or {}).get("id")
                or data.get("bot_id")
                or data.get("id")
                or (payload.get("bot", {}) or {}).get("id")
                or payload.get("id")
            )
            tm = registry.get_manager(bot_id=bot_id)
            status = (
                mapped_status
                or data.get("status")
                or (payload.get("bot", {}) or {}).get("status")
                or payload.get("status")
            )
            sub_code = data.get("sub_code") or payload.get("sub_code")

            if status == "joining_call":
                logger.info(f"Bot {bot_id} is joining the meeting")

            elif status == "in_call":
                logger.info(f"Bot {bot_id} successfully joined the meeting")

            elif status == "in_call_recording":
                logger.info(f"Bot {bot_id} is now recording")

            elif status == "call_ended":
                logger.info(f"Bot {bot_id} call ended")
                try:
                    await tm.remove_cleanup_ingest(ti=ti)
                    registry.remove_manager(bot_id=bot_id)
                except Exception:
                    logger.exception("Error while handling call_ended cleanup")

            elif status == "done":
                logger.info(f"Bot {bot_id} finished successfully")
                try:
                    await tm.remove_cleanup_ingest(ti=ti)
                    registry.remove_manager(bot_id=bot_id)
                except Exception:
                    logger.exception("Error while handling done cleanup")
 
            elif status == "fatal":
                logger.error(f"Bot {bot_id} encountered a fatal error")
                if sub_code:
                    logger.error(f"Fatal error reason: {sub_code}")
                try:
                    await tm.remove_cleanup_ingest(ti=ti)
                    registry.remove_manager(bot_id=bot_id)
                except Exception:
                    logger.exception("Error while handling fatal cleanup")

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
        tm = registry.get_manager(bot_id=bot_id)

        if event_type == "transcript.data":
            tm.monitor.record_activity()
            tm.monitor.record_transcript()
            words = payload["data"]["data"]["words"]
            speaker = payload["data"]["data"]["participant"]["name"]
            spoken_text = " ".join([w["text"] for w in words])
            
            start_time = words[0]["start_timestamp"]["relative"]
            end_time = words[-1]["end_timestamp"]["relative"]
        
            print(f"Processing audio segment: {start_time}s to {end_time}s from {speaker}")
            
            
            if tm._is_duplicate_audio_segment(start_time, end_time, speaker):
                print(f"Skipping duplicate audio segment from {speaker}")
                return {"status": "ok"}
            
            logger.info(f"Transcribed text from {speaker}: {spoken_text}")
            tm.writer.save_line(speaker, spoken_text)
            
            if "scooby" in spoken_text.lower():
                logger.info(f"Scooby mentioned by {speaker}: {spoken_text}")
                try:
                    logger.debug(f"Sending to Gemini: {spoken_text}")
                    await tm.model.connect_to_gemini(text=spoken_text)
                    logger.debug("Sent to Gemini successfully")
                except Exception as e:
                    logger.exception(f"Error sending to Gemini: {e}")

            else:
                tm.model.chat_history.append(
                    {"role": "user", "content": spoken_text.strip(), "type": "audio_response"}
                )

        elif event_type == "participant_events.join":
            tm.monitor.record_activity()
            participant_data = payload["data"]["data"]["participant"]
            action = payload["data"]["data"]["action"]

            if action == "join":
                tm.pm.add(participant_data)
                try:
                    tm.model.participants = list(tm.pm.list)
                except Exception:
                    pass
                logger.info(f"Total participants: {len(tm.pm.list)}")

        elif event_type == "participant_events.leave":
            tm.monitor.record_activity()
            participant_data = payload["data"]["data"]["participant"]
            participant_id = participant_data["id"]
            participant_name = participant_data["name"]

            if participant_name.lower() != "scooby":
                tm.pm.mark_left(participant_id)
                try:
                    tm.model.participants = list(tm.pm.list)
                except Exception:
                    pass
                p = tm.pm.get(participant_id)
                if p:
                    logger.info(f"Participant left: {p['name']}")

        else:
            logger.warning(f"Unhandled realtime event: {event_type}")

    except Exception as e:
        logger.exception(f"Error processing realtime webhook: {e}")

    return {"status": "ok"}
