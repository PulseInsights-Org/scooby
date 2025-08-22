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



rb = RecallBot()
app = FastAPI()
cm = ConnectionManager()
model = GeminiLive(connection_manager=cm)


current_bot_id = None
current_meeting_url = None
participants = []  
transcripts_enabled = False


# Request models
class AddScoobyRequest(BaseModel):
    meeting_url: str
    isTranscript: bool = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Directory to store transcripts
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")

def _safe_name(value: str) -> str:
    try:
        s = str(value or "unknown")
        # Remove or replace characters invalid on Windows filenames
        for ch in '<>:"/\\|?*':
            s = s.replace(ch, '-')
        # Also strip spaces at ends
        return s.strip().replace(os.sep, '-')
    except Exception:
        return "unknown"

def _save_transcript_line(bot_id: str, meeting_id: str, speaker: str, text: str):
    try:
        # Respect transcript preference for the single active bot
        if not transcripts_enabled:
            return
        if not os.path.exists(TRANSCRIPTS_DIR):
            os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
        safe_bot = _safe_name(bot_id)
        safe_meeting = _safe_name(meeting_id)
        file_path = os.path.join(TRANSCRIPTS_DIR, f"{safe_bot}_{safe_meeting}.txt")
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(f"{speaker}: {text}\n")
    except Exception as e:
        print(f"Error saving transcript: {e}")

# Static files (CSS/JS)
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Effective error handling 

# todo - cors handling

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        # Sync participants state to model for tools
        try:
            model.participants = list(participants)
        except Exception:
            pass
            
    except Exception as e:
        print(f"Error managing participant: {e}")

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

def remove_bot_context():
    try:
        global current_bot_id, current_meeting_url, transcripts_enabled
        reset_participants()
        current_bot_id = None
        current_meeting_url = None
        transcripts_enabled = False
        # Also clear the model's active bot id
        try:
            model.bot_id = None
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

# todo - change to pydantic base model of request type and add meeting url as parameter

@app.get("/")
async def bot_html(request: Request):
    return templates.TemplateResponse("bot.html", {"request": request})
    
    
@app.post("/add_scooby")
async def add_scooby_bot(payload: AddScoobyRequest):
    meeting_url = payload.meeting_url
    # New optional flag, defaults to False (handled by model)
    is_transcript = payload.isTranscript
    bot_id = await rb.add_bots(meeting_url)
    # Overwrite any existing state to focus on a single bot
    if bot_id:
        global current_bot_id, current_meeting_url, transcripts_enabled
        current_bot_id = bot_id
        current_meeting_url = meeting_url
        transcripts_enabled = is_transcript
        reset_participants()
        # Propagate bot id to model so tools can use it
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


# refer recall docs to add more context to model
# 1. participant data                 - done
# 2. left event and join event        - done
# 3. answer in chat                   - going onn
# 4. screen share                     - pending
# 5. Include transcription feature    - pending
 
@app.post("/api/webhook/recall/bot-status")
async def recall_bot_status_webhook(request: Request):
    """
    Handle Bot Status Change Webhooks from Recall.ai
    These are configured separately in the Recall dashboard
    """
    print("Received BOT STATUS webhook from Recall.ai")
    try:
        payload = await request.json()
        print("Bot Status Payload:", payload)
        
        event_type = payload.get("type")  # Note: different structure than realtime webhooks
        data = payload.get("data", {})
        
        if event_type == "bot.status_change":
            bot_id = data.get("id")
            status = data.get("status")
            sub_code = data.get("sub_code")
            # Try to capture a meeting id if available for logging
            meeting_id = (
                data.get("meeting_id")
                or (data.get("meeting") or {}).get("id")
                or current_meeting_url
                or "unknown"
            )
            
            print(f"Bot {bot_id} status changed to: {status}")
            if sub_code:
                print(f"Sub code: {sub_code}")
            
            # Ignore statuses for non-current bot (single bot focus)
            if current_bot_id and bot_id != current_bot_id:
                print(f"Ignoring status for non-current bot {bot_id}")
                return {"status": "ok"}

            # Handle different bot statuses for the current bot
            if status == "joining_call":
                print(f"Bot {bot_id} is joining the meeting")
                # Bot is attempting to join
                _save_transcript_line(bot_id, meeting_id, "BOT_STATUS", f"Bot [id : {bot_id}] is joining the meeting")
                
            elif status == "in_call":
                print(f"Bot {bot_id} successfully joined the meeting")
                # Bot has successfully joined and is in the call
                _save_transcript_line(bot_id, meeting_id, "BOT_STATUS", f"Bot [id : {bot_id}] joined the meeting")
                
            elif status == "in_call_recording":
                print(f"Bot {bot_id} is now recording")
                # Bot is actively recording
                _save_transcript_line(bot_id, meeting_id, "BOT_STATUS", f"Bot [id : {bot_id}] started recording")
                
            elif status == "call_ended":
                print(f"Bot {bot_id} call ended")
                # Call has ended normally
                _save_transcript_line(bot_id, meeting_id, "BOT_STATUS", "Call ended")
                remove_bot_context()
                print_active_bots()
                
            elif status == "done":
                print(f"Bot {bot_id} finished successfully")
                # Bot completed successfully
                _save_transcript_line(bot_id, meeting_id, "BOT_STATUS", f"Bot [id : {bot_id}] finished successfully")
                remove_bot_context()
                print_active_bots()
                
            elif status == "fatal":
                print(f"Bot {bot_id} encountered a fatal error")
                if sub_code:
                    print(f"Fatal error reason: {sub_code}")
                # Bot failed with fatal error
                _save_transcript_line(bot_id, meeting_id, "BOT_STATUS", f"Bot fatal error: {sub_code or 'unknown reason'}")
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
    """
    Handle Real-Time Webhooks from Recall.ai (transcript, participant events)
    """
    print("Received REALTIME webhook from Recall.ai")
    try:
        payload = await request.json()
        print("Realtime Payload:", payload)
        
        event_type = payload.get("event")
        data = payload.get("data", {})
        bot_info = data.get("bot", {})
        bot_id = bot_info.get("id")
        # Try to extract a meeting identifier from common fields
        meeting_id = (
            bot_info.get("meeting_id")
            or data.get("meeting_id")
            or (data.get("meeting") or {}).get("id")
            or current_meeting_url
            or "unknown"
        )

        # If no bot added yet via /add_scooby, ignore realtime events
        if current_bot_id is None:
            print("No current bot set; ignoring realtime event")
            return {"status": "ok"}

        # Ignore events for non-current bot to keep single-bot context simple
        if current_bot_id and bot_id != current_bot_id:
            print(f"Ignoring realtime event for non-current bot {bot_id}")
            return {"status": "ok"}
        
        if event_type == "transcript.data":
            words = payload["data"]["data"]["words"]
            speaker = payload["data"]["data"]["participant"]["name"]
            spoken_text = " ".join([w["text"] for w in words])
            print(f"Transcribed text from {speaker}: {spoken_text}")
            _save_transcript_line(bot_id, meeting_id, speaker, spoken_text)
    
            
            if "scooby" in spoken_text.lower():
                print(f"Scooby mentioned by {speaker}: {spoken_text}")
                try:
                    print(f"Sending to Gemini: {spoken_text}")
                    await model.connect_to_gemini(text=spoken_text)
                    print("Sent to Gemini successfully")
                except Exception as e:
                    print(f"Error sending to Gemini: {e}")
        
        elif event_type == "participant_events.join":
            participant_data = payload["data"]["data"]["participant"]
            action = payload["data"]["data"]["action"]
            
            if action == "join":
                add_participant(participant_data)
                print(f"Total participants: {len(participants)}")
                print_active_bots()
                # Log to transcript
                _save_transcript_line(
                    bot_id,
                    meeting_id,
                    "INFO : PARTICIPANT",
                    f"JOINED : {participant_data.get('name')} ({participant_data.get('id')})"
                )
        
        elif event_type == "participant_events.leave":
            participant_data = payload["data"]["data"]["participant"]
            participant_id = participant_data["id"]
            participant_name = participant_data["name"]
            
            # Note: Don't handle bot leaving here, use bot status webhooks instead
            if participant_name.lower() != "scooby":
                participant = get_participant_by_id(participant_id)
                if participant:
                    participant['status'] = 'left'
                    print(f"Participant left: {participant['name']}")
            # Sync participants state to model for tools
            try:
                model.participants = list(participants)
            except Exception:
                pass
            # Log to transcript
            _save_transcript_line(
                bot_id,
                meeting_id,
                "INFO : PARTICIPANT",
                f"LEFT: {participant_name} ({participant_id})"
            )
            print_active_bots()
        
        else:
            print(f"Unhandled realtime event: {event_type}")

    except Exception as e:
        print(f"Error processing realtime webhook: {e}")

    return {"status": "ok"}
