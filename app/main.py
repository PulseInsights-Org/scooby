from fastapi import FastAPI, Request
from pydantic import BaseModel
from app.service.recall_bot import RecallBot
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from app.service.gemini_live import GeminiLive
from app.core.manage_connections import ConnectionManager
from fastapi import WebSocket, WebSocketDisconnect
import os



rb = RecallBot()
app = FastAPI()
cm = ConnectionManager()
model = GeminiLive(connection_manager=cm)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# Effective error handling 

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
async def add_scooby_bot(request : Request):
    
    data = await request.json()
    meeting_url = data.get("meeting_url")
    bot_id = await rb.add_bots(meeting_url)
    return None

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
    finally:
        cm.remove_connection(connection_id)


# refer recall docs to add more context to model
# 1. participant data
# 2. left event and join event
# 3. answer in chat
# 4. screen share
 
@app.post("/api/webhook/recall")
async def recall_webhook(request: Request):
    
    print("Received webhook from Recall.ai")
    try:
        payload = await request.json()
        
        event_type = payload.get("event")
        
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
            
        
        # elif event_type == "participant_events.join":
        #     participant_data = payload["data"]["data"]["participant"]
        #     action = payload["data"]["data"]["action"]
            
        #     if action == "join":
        #         add_participant(participant_data)
        #         logger.info(f"Participant joined: {participant_data['name']}")
                
        #         logger.info(f"Total participants: {len(participants)}")
        #         for p in participants:
        #             logger.info(f"  - {p['name']} (ID: {p['id']}, Host: {p['is_host']})")
        
        # elif event_type == "participant_events.leave":
        #     participant_data = payload["data"]["data"]["participant"]
        #     participant_id = participant_data["id"]
            
        #     participant = get_participant_by_id(participant_id)
        #     if participant:
        #         participant['status'] = 'left'
        #         print(f"Participant left: {participant['name']}")
                
        #         if participant['name'].lower() == 'pulse' and pulse_gemini_handler:
        #             print("Pulse participant left meeting - cleaning up handler")
        #             await pulse_gemini_handler.cleanup()
        #             pulse_gemini_handler = None
        #         elif participant['name'].lower() == 'arya' and arya_gemini_handler:
        #             print("Arya participant left meeting - cleaning up handler")
        #             await arya_gemini_handler.cleanup()
        #             arya_gemini_handler = None
        
        else:
            print(f"Received unhandled event type: {event_type}")

    except Exception as e:
        print(f"Error processing webhook: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")

    return {"status": "ok"}
