from turtle import mode
from fastapi import FastAPI, Request
from pydantic import BaseModel
from app.service.recall_bot import RecallBot
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from app.service.gemini_live import GeminiLive
from app.core.manage_connections import ConnectionManager
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
import os
import logging
import asyncio
from app.service.transcript_ingestion import TranscriptIngestion

rb = RecallBot()
app = FastAPI()
cm = ConnectionManager()
model = GeminiLive(connection_manager=cm)
ti = TranscriptIngestion(org_id="")

# Configure logging early so all modules use it
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

current_bot_id = None
current_meeting_url = None
participants = []  
transcripts_enabled = False
processed_audio_segments = set()
current_x_org_id = None
current_tenant_id = None
# Guard to prevent duplicate transcript ingestion
transcript_ingestion_lock = asyncio.Lock()
transcript_ingested_bots = set()

class MeetingRequest(BaseModel):
    meeting_url: str
    isTranscript: bool = False
    x_org_id: str 
    tenant_id: str 
    saveTranscript: bool = True

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def _safe_name(value: str) -> str:
    try:
        s = str(value or "unknown")
        for ch in '<>:"/\\|?*':
            s = s.replace(ch, '-')
        return s.strip().replace(os.sep, '-')
    except Exception:
        return "unknown"

def _save_transcript_line(bot_id: str, speaker: str, text: str):
    try:
        if not transcripts_enabled:
            return
        if not os.path.exists(TRANSCRIPTS_DIR):
            os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        safe_bot = _safe_name(bot_id)
        safe_meeting = _safe_name(current_meeting_url or "meeting")
        file_path = os.path.join(TRANSCRIPTS_DIR, f"{safe_bot}_{safe_meeting}.txt")
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"{speaker}: {text}\n")
    except Exception as e:
        print(f"Error saving transcript: {e}")

def _transcript_file_path(bot_id: str) -> str:
    try:
        safe_bot = _safe_name(bot_id)
        safe_meeting = _safe_name(current_meeting_url or "meeting")
        return os.path.join(TRANSCRIPTS_DIR, f"{safe_bot}_{safe_meeting}.txt")
    except Exception:
        return os.path.join(TRANSCRIPTS_DIR, "unknown_meeting.txt")

async def _ingest_and_cleanup_transcript(bot_id: str):
    try:
        if not transcripts_enabled:
            return
        # Ensure only one ingestion per bot even if multiple status events fire
        async with transcript_ingestion_lock:
            if bot_id in transcript_ingested_bots:
                logger.info("Transcript ingestion already performed for bot %s; skipping", bot_id)
                return
            transcript_ingested_bots.add(bot_id)
        transcript_path = _transcript_file_path(bot_id)
        if not os.path.exists(transcript_path):
            logger.warning("Transcript file not found at %s", transcript_path)
            return
        logger.info("Starting transcript ingestion for %s", transcript_path)
        res = await ti.ingest_transcript(current_x_org_id, current_tenant_id, transcript_path)
        logger.info("Transcript ingestion result: %s", res)
        if res and res.get("success"):
            try:
                os.remove(transcript_path)
                logger.info("Deleted transcript file %s", transcript_path)
            except Exception as de:
                logger.error("Failed to delete transcript file %s: %s", transcript_path, de)
    except Exception as e:
        logger.exception("Error during transcript ingestion: %s", e)

def _is_duplicate_audio_segment(start_time: float, end_time: float, speaker: str) -> bool:
    """Simple check if this exact audio segment was already processed"""
    segment_key = f"{start_time}:{end_time}:{speaker}"
    
    if segment_key in processed_audio_segments:
        print(f"Duplicate audio segment detected: {start_time}s to {end_time}s from {speaker}")
        return True
        
    processed_audio_segments.add(segment_key)
    return False


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def bot_html(request: Request):
    return templates.TemplateResponse("bot.html", {"request": request})
    
    
@app.post("/add_scooby")
async def add_scooby_bot(request: MeetingRequest):
    global current_bot_id, current_meeting_url, transcripts_enabled, current_x_org_id, current_tenant_id
    
    if current_bot_id is not None:
        return {
            "message" : "Scooby Bot already exists, Please remove and try again"
        }
    
    meeting_url = request.meeting_url
    is_transcript = request.saveTranscript or request.isTranscript
    bot_id = await rb.add_bots(meeting_url)
    if bot_id:
        
        current_bot_id = bot_id
        current_meeting_url = meeting_url
        transcripts_enabled = bool(is_transcript)
        current_x_org_id = request.x_org_id
        current_tenant_id = request.tenant_id
        reset_participants()

        processed_audio_segments.clear()
        # Reset ingestion guard when a new bot is added
        transcript_ingested_bots.clear()
        try:
            model.bot_id = bot_id
        except Exception:
            pass
        print_active_bots()
    return {"bot_id": bot_id}

@app.websocket("/ws")
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
            data = await websocket.receive_text()

    except WebSocketDisconnect:
        print(f"WebSocket {connection_id} disconnected")
        cm.remove_connection(connection_id)
    except Exception as e:
        print(f"WebSocket error for {connection_id}: {e}")
        cm.remove_connection(connection_id)

 
@app.post("/api/webhook/recall/bot-status")
async def recall_bot_status_webhook(request: Request):
    print("Received BOT STATUS webhook from Recall.ai")
    try:
        payload = await request.json()
        print("Bot Status Payload:", payload)
        
        # Support both legacy ('type','status') and new ('event','data.code') payloads
        event_type = payload.get("type") or payload.get("event")
        data = payload.get("data", {})
        bot_id = data.get("id") or data.get("bot", {}).get("id")
        status = data.get("status") or (data.get("data", {}) or {}).get("code")
        sub_code = data.get("sub_code") or (data.get("data", {}) or {}).get("sub_code")
        
        if event_type == "bot.status_change" or status is not None:
            
            print(f"Bot {bot_id} status changed to: {status}")
            if sub_code:
                print(f"Sub code: {sub_code}")
            
            if current_bot_id and bot_id != current_bot_id:
                print(f"Ignoring status for non-current bot {bot_id}")
                return {"status": "ok"}

            if status == "joining_call":
                print(f"Bot {bot_id} is joining the meeting")
                _save_transcript_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] is joining the meeting")
                
            elif status == "in_call":
                print(f"Bot {bot_id} successfully joined the meeting")
                _save_transcript_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] joined the meeting")
                
            elif status == "in_call_recording":
                print(f"Bot {bot_id} is now recording")
                _save_transcript_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] started recording")
                
            elif status == "call_ended":
                print(f"Bot {bot_id} call ended")
                _save_transcript_line(bot_id, "BOT_STATUS", "Call ended")
                # Ingest transcript before clearing context
                try:
                    await _ingest_and_cleanup_transcript(bot_id)
                finally:
                    remove_bot_context()
                    print_active_bots()
                
            elif status == "done":
                print(f"Bot {bot_id} finished successfully")
                _save_transcript_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] finished successfully")
                try:
                    await _ingest_and_cleanup_transcript(bot_id)
                finally:
                    rb.remove_bot_context()
                    print_active_bots()
                
            elif status == "fatal":
                print(f"Bot {bot_id} encountered a fatal error")
                if sub_code:
                    print(f"Fatal error reason: {sub_code}")
                _save_transcript_line(bot_id, "BOT_STATUS", f"Bot fatal error: {sub_code or 'unknown reason'}")
                try:
                    await _ingest_and_cleanup_transcript(bot_id)
                finally:
                    remove_bot_context()
                    print_active_bots()
                
            else:
                print(f"Unhandled bot status: {status}")
        
        else:
            print(f"Unhandled bot status event type: {event_type}")

    except Exception as e:
        print(f"Error processing bot status webhook: {e}")

    return {"status": "ok"}


@app.post("/api/webhook/recall")
async def recall_webhook(request: Request):
    print("Received REALTIME webhook from Recall.ai")
    try:
        payload = await request.json()
        print("Realtime Payload:", payload)
        
        event_type = payload.get("event")
        data = payload.get("data", {})
        bot_info = data.get("bot", {})
        bot_id = bot_info.get("id")

        if current_bot_id is None:
            print("No current bot set; ignoring realtime event")
            return {"status": "ok"}

        if current_bot_id and bot_id != current_bot_id:
            print(f"Ignoring realtime event for non-current bot {bot_id}")
            return {"status": "ok"}
        
        if event_type == "transcript.data":
            words = payload["data"]["data"]["words"]
            speaker = payload["data"]["data"]["participant"]["name"]
            spoken_text = " ".join([w["text"] for w in words])
            
            # Get audio segment timestamps for deduplication
            start_time = words[0]["start_timestamp"]["relative"]
            end_time = words[-1]["end_timestamp"]["relative"]
            
            print(f"Processing audio segment: {start_time}s to {end_time}s from {speaker}")
            
            if _is_duplicate_audio_segment(start_time, end_time, speaker):
                print(f"Skipping duplicate audio segment from {speaker}")
                return {"status": "ok"}
            
            print(f"Transcribed text from {speaker}: {spoken_text}")
            _save_transcript_line(bot_id, speaker, spoken_text)
    
            
            if "scooby" in spoken_text.lower():
                print(f"Scooby mentioned by {speaker}: {spoken_text}")
                try:
                    print(f"Sending to Gemini: {spoken_text}")
                    await model.connect_to_gemini(text=spoken_text)
                    print("Sent to Gemini successfully")
                except Exception as e:
                    print(f"Error sending to Gemini: {e}")
        
            else:
                model.chat_history.append(
                   { "role": "user",
                    "content": spoken_text.strip(),
                    "type": "audio_response"}
                )
        elif event_type == "participant_events.join":
            participant_data = payload["data"]["data"]["participant"]
            action = payload["data"]["data"]["action"]
            
            if action == "join":
                add_participant(participant_data)
                print(f"Total participants: {len(participants)}")
                print_active_bots()
                _save_transcript_line(
                    bot_id,
                    "INFO : PARTICIPANT",
                    f"JOINED : {participant_data.get('name')} ({participant_data.get('id')})"
                )
        
        elif event_type == "participant_events.leave":
            participant_data = payload["data"]["data"]["participant"]
            participant_id = participant_data["id"]
            participant_name = participant_data["name"]
            
            if participant_name.lower() != "scooby":
                participant = get_participant_by_id(participant_id)
                if participant:
                    participant['status'] = 'left'
                    print(f"Participant left: {participant['name']}")
            try:
                model.participants = list(participants)
            except Exception:
                pass
            _save_transcript_line(
                bot_id,
                "INFO : PARTICIPANT",
                f"LEFT: {participant_name} ({participant_id})"
            )
            print_active_bots()
        
        else:
            print(f"Unhandled realtime event: {event_type}")

    except Exception as e:
        print(f"Error processing realtime webhook: {e}")

    return {"status": "ok"}

def get_participant_by_id(participant_id):
    try:
        return next((p for p in participants if p['id'] == participant_id), None)
    except Exception as e:
        print(f"Error getting participant: {e}")
        return None

def reset_participants():
    try:
        participants.clear()
        try:
            model.participants = []
        except Exception:
            pass
        print("Participant context reset")
    except Exception as e:
        print(f"Error resetting participants: {e}")

def add_participant(participant_data):
        try:
            participant_id = participant_data.get('id')
            participant_name = participant_data.get('name')
            
            if not participant_id or not participant_name:
                print(f"Invalid participant data: {participant_data}")
                return
            
            existing_participant = next((p for p in participants if p['id'] == participant_id), None)
            
            if not existing_participant:
                participants.append({
                    'id': participant_id,
                    'name': participant_name,
                    'is_host': participant_data.get('is_host', False),
                    'platform': participant_data.get('platform', 'unknown'),
                    'extra_data': participant_data.get('extra_data', {}),
                    'status': 'joined'
                })
                print(f"Added participant: {participant_name}")
            else:
                existing_participant.update({
                    'name': participant_name,
                    'is_host': participant_data.get('is_host', False),
                    'platform': participant_data.get('platform', 'unknown'),
                    'extra_data': participant_data.get('extra_data', {}),
                    'status': 'joined'
                })
                print(f"Updated participant: {participant_name}")
            try:
                model.participants = list(participants)
            except Exception:
                pass
                
        except Exception as e:
            print(f"Error managing participant: {e}")


def remove_bot_context():
        try:
            global current_bot_id, current_meeting_url, transcripts_enabled
            reset_participants()
            # Reset audio segment cache
            processed_audio_segments.clear()
            # Reset transcript ingestion guard
            transcript_ingested_bots.clear()
            current_bot_id = None
            current_meeting_url = None
            transcripts_enabled = False
            try:
                model.bot_id = None
                model.chat_history = []
                model.conversation_history = []
                try:
                    model.current_transcription = ""
                except Exception:
                    pass
            except Exception:
                pass
            print("Cleared current bot context")
        except Exception as e:
            print(f"Error removing bot context: {e}")


def print_active_bots():
        try:
            print(f"Current active bot: {current_bot_id}")
        except Exception as e:
            print(f"Error printing active bots: {e}")