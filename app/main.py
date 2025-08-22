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

# Participants scoped by bot_id so multiple meetings can run concurrently
participants_by_bot = {}


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

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

def add_participant(bot_id: str, participant_data):
    try:
        participant_id = participant_data.get('id')
        participant_name = participant_data.get('name')
        
        if not participant_id or not participant_name:
            print(f"Invalid participant data: {participant_data}")
            return
        
        if bot_id not in participants_by_bot:
            participants_by_bot[bot_id] = []
        participants = participants_by_bot[bot_id]

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
            
    except Exception as e:
        print(f"Error managing participant: {e}")

def get_participant_by_id(bot_id: str, participant_id):
    try:
        participants = participants_by_bot.get(bot_id, [])
        return next((p for p in participants if p['id'] == participant_id), None)
    except Exception as e:
        print(f"Error getting participant: {e}")
        return None

def reset_participants(bot_id: str):
    try:
        if bot_id in participants_by_bot:
            participants_by_bot[bot_id].clear()
        else:
            participants_by_bot[bot_id] = []
        print(f"Participant context reset for bot_id={bot_id}")
    except Exception as e:
        print(f"Error resetting participants: {e}")


def remove_bot_context(bot_id: str):
    try:
        removed = participants_by_bot.pop(bot_id, None)
        print(f"Removed bot context for bot_id={bot_id}. Present before remove: {removed is not None}")
    except Exception as e:
        print(f"Error removing bot context: {e}")


def print_active_bots():
    try:
        active_ids = list(participants_by_bot.keys())
        print(f"Active bot IDs ({len(active_ids)}): {active_ids}")
    except Exception as e:
        print(f"Error printing active bots: {e}")


def ensure_bot_context(bot_id: str):
    """Create an empty participant list for a bot if it's missing.
    This allows us to receive webhooks for bots started elsewhere and still track state.
    """
    try:
        if bot_id and bot_id not in participants_by_bot:
            participants_by_bot[bot_id] = []
            print(f"Initialized context for bot_id={bot_id} from webhook event")
    except Exception as e:
        print(f"Error ensuring bot context: {e}")

# todo - change to pydantic base model of request type and add meeting url as parameter

@app.get("/")
async def bot_html(request: Request):
    return templates.TemplateResponse("bot.html", {"request": request})
    
    
@app.post("/add_scooby")
async def add_scooby_bot(request : Request):
    
    data = await request.json()
    meeting_url = data.get("meeting_url")
    bot_id = await rb.add_bots(meeting_url)
    # Initialize an empty participant list for this bot/meeting
    if bot_id:
        participants_by_bot[bot_id] = []
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
    except Exception as e:
        print(f"WebSocket error for {connection_id}: {e}")


# refer recall docs to add more context to model
# 1. participant data                 - done
# 2. left event and join event        - done
# 3. answer in chat                   - going onn
# 4. screen share                     - pending
 
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
            
            print(f"Bot {bot_id} status changed to: {status}")
            if sub_code:
                print(f"Sub code: {sub_code}")
            
            # Handle different bot statuses
            if status == "joining_call":
                print(f"Bot {bot_id} is joining the meeting")
                # Bot is attempting to join
                
            elif status == "in_call":
                print(f"Bot {bot_id} successfully joined the meeting")
                # Bot has successfully joined and is in the call
                
            elif status == "in_call_recording":
                print(f"Bot {bot_id} is now recording")
                # Bot is actively recording
                
            elif status == "call_ended":
                print(f"Bot {bot_id} call ended")
                # Call has ended normally
                remove_bot_context(bot_id)
                print_active_bots()
                
            elif status == "done":
                print(f"Bot {bot_id} finished successfully")
                # Bot completed successfully
                remove_bot_context(bot_id)
                print_active_bots()
                
            elif status == "fatal":
                print(f"Bot {bot_id} encountered a fatal error")
                if sub_code:
                    print(f"Fatal error reason: {sub_code}")
                # Bot failed with fatal error
                remove_bot_context(bot_id)
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
        
        if event_type == "transcript.data":
            words = payload["data"]["data"]["words"]
            speaker = payload["data"]["data"]["participant"]["name"]
            spoken_text = " ".join([w["text"] for w in words])
            print(f"Transcribed text from {speaker}: {spoken_text}")
    
            
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
                add_participant(bot_id, participant_data)
                print(f"Total participants for bot {bot_id}: {len(participants_by_bot.get(bot_id, []))}")
                print_active_bots()
        
        elif event_type == "participant_events.leave":
            participant_data = payload["data"]["data"]["participant"]
            participant_id = participant_data["id"]
            participant_name = participant_data["name"]
            
            # Note: Don't handle bot leaving here, use bot status webhooks instead
            if participant_name.lower() != "scooby":
                participant = get_participant_by_id(bot_id, participant_id)
                if participant:
                    participant['status'] = 'left'
                    print(f"Participant left: {participant['name']}")
                print_active_bots()
        
        else:
            print(f"Unhandled realtime event: {event_type}")

    except Exception as e:
        print(f"Error processing realtime webhook: {e}")

    return {"status": "ok"}
