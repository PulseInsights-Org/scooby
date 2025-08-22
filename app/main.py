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
from app.service.participants import ParticipantsManager
from app.utils import TranscriptWriter, BotContext


rb = RecallBot()
app = FastAPI()
cm = ConnectionManager()
model = GeminiLive(connection_manager=cm)


current_bot_id = None
current_meeting_url = None
transcripts_enabled = False


bot_context = BotContext()
participants_manager = ParticipantsManager()

participants = participants_manager.list
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(BASE_DIR, "transcripts")
transcript_writer = TranscriptWriter(
    enabled_getter=lambda: transcripts_enabled,
    transcripts_dir=TRANSCRIPTS_DIR,
    meeting_url_getter=lambda: current_meeting_url,
)

class MeetingRequest(BaseModel):
    meeting_url: str
    isTranscript: bool = False
    


templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# todo - cors handling

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

    

# todo - change to pydantic base model of request type and add meeting url as parameter

@app.get("/")
async def bot_html(request: Request):
    return templates.TemplateResponse("bot.html", {"request": request})
    
    
@app.post("/add_scooby")
async def add_scooby_bot(request: MeetingRequest):
    meeting_url = request.meeting_url
    is_transcript = request.isTranscript
    bot_id = await rb.add_bots(meeting_url)
    if bot_id:
        global current_bot_id, current_meeting_url, transcripts_enabled
        current_bot_id = bot_id
        current_meeting_url = meeting_url
        transcripts_enabled = is_transcript
        # keep BotContext in sync
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
        # Propagate bot id to model so tools can use it
        try:
            model.bot_id = bot_id
        except Exception:
            pass
        bot_context.print_active_bot()
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

# to do
# refer recall docs to add more context to model
# 1. participant data                 - done
# 2. left event and join event        - done
# 3. answer in chat                   - done
# 4. screen share                     - pending
# 5. Include transcription feature    - done
 
@app.post("/api/webhook/recall/bot-status")
async def recall_bot_status_webhook(request: Request):
    print("Received BOT STATUS webhook from Recall.ai")
    try:
        payload = await request.json()
        print("Bot Status Payload:", payload)
        global current_bot_id, current_meeting_url, transcripts_enabled
        
        event_type = payload.get("type")
        data = payload.get("data", {})
        
        if event_type == "bot.status_change":
            bot_id = data.get("id")
            status = data.get("status")
            sub_code = data.get("sub_code")
            
            print(f"Bot {bot_id} status changed to: {status}")
            if sub_code:
                print(f"Sub code: {sub_code}")
            
            if current_bot_id and bot_id != current_bot_id:
                print(f"Ignoring status for non-current bot {bot_id}")
                return {"status": "ok"}

            # Handle different bot statuses for the current bot
            if status == "joining_call":
                print(f"Bot {bot_id} is joining the meeting")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] is joining the meeting")
                
            elif status == "in_call":
                print(f"Bot {bot_id} successfully joined the meeting")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] joined the meeting")
                
            elif status == "in_call_recording":
                print(f"Bot {bot_id} is now recording")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] started recording")
                
            elif status == "call_ended":
                print(f"Bot {bot_id} call ended")
                transcript_writer.save_line(bot_id, "BOT_STATUS", "Call ended")
                try:
                    participants_manager.reset()
                    try:
                        model.participants = []
                    except Exception:
                        pass
                    current_bot_id = None
                    current_meeting_url = None
                    transcripts_enabled = False
                    bot_context.clear()
                    BotContext.remove_model_context(model)
                except Exception as _:
                    pass
                bot_context.print_active_bot()
                
            elif status == "done":
                print(f"Bot {bot_id} finished successfully")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot [id : {bot_id}] finished successfully")
                try:
                    participants_manager.reset()
                    try:
                        model.participants = []
                    except Exception:
                        pass
                    current_bot_id = None
                    current_meeting_url = None
                    transcripts_enabled = False
                    bot_context.clear()
                    BotContext.remove_model_context(model)
                except Exception as _:
                    pass
                bot_context.print_active_bot()
                
            elif status == "fatal":
                print(f"Bot {bot_id} encountered a fatal error")
                if sub_code:
                    print(f"Fatal error reason: {sub_code}")
                transcript_writer.save_line(bot_id, "BOT_STATUS", f"Bot fatal error: {sub_code or 'unknown reason'}")
                try:
                    participants_manager.reset()
                    try:
                        model.participants = []
                    except Exception:
                        pass
                    current_bot_id = None
                    current_meeting_url = None
                    transcripts_enabled = False
                    bot_context.clear()
                    BotContext.remove_model_context(model)
                except Exception as _:
                    pass
                bot_context.print_active_bot()
                
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
            print(f"Transcribed text from {speaker}: {spoken_text}")
            transcript_writer.save_line(bot_id, speaker, spoken_text)
    
            
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
                participants_manager.add(participant_data)
                try:
                    model.participants = list(participants_manager.list)
                except Exception:
                    pass
                print(f"Total participants: {len(participants_manager.list)}")
                bot_context.print_active_bot()
                transcript_writer.save_line(
                    bot_id,
                    "INFO : PARTICIPANT",
                    f"JOINED : {participant_data.get('name')} ({participant_data.get('id')})"
                )
        
        elif event_type == "participant_events.leave":
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
                    print(f"Participant left: {p['name']}")
            transcript_writer.save_line(
                bot_id,
                "INFO : PARTICIPANT",
                f"LEFT: {participant_name} ({participant_id})"
            )
            bot_context.print_active_bot()
        
        else:
            print(f"Unhandled realtime event: {event_type}")

    except Exception as e:
        print(f"Error processing realtime webhook: {e}")

    return {"status": "ok"}
