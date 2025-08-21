from google import genai
from app.core.manage_connections import ConnectionManager
import base64

class GeminiLive():
    
    def __init__(self, api_key = "AIzaSyBUjH-PkLSZzyDxFXeTlTw9s8PaZq2nNPc", connection_manager: ConnectionManager = None):
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.0-flash-live-001"
        self.config = {
            "response_modalities": ["AUDIO"],
            "temperature": 0
        }
        self.connection_manager = connection_manager
    
    async def _async_enumerate(self, aiterable):
        n = 0
        async for item in aiterable:
            yield n, item
            n += 1
    
    # 1. add tool call
    # 2. Add coversation history
    # 3. voice, temp, prompt, transcription etc -> slaient features
    
    async def connect_to_gemini(self, text):
        async with self.client.aio.live.connect(
            model = self.model,
            config=self.config,
        ) as connection : 
            message = text
            print(message)
            await connection.send_client_content(
                turns={"role": "user", "parts": [{"text": message}]}, turn_complete=True
            )
            
            turn = connection.receive()
            async for n, response in self._async_enumerate(turn):
                if response.data is not None and self.connection_manager is not None:
                    try:
                        encoded = base64.b64encode(response.data).decode("ascii")
                    except Exception as encode_err:
                        print(f"Error base64-encoding audio chunk: {encode_err}")
                        encoded = None
                    if encoded:
                        print("sending audio")
                        await self.connection_manager.send_to_all({
                            "type": "audio",
                            "data": encoded,
                            "bot_type": "scooby"
                        })
                if n ==0:
                    print(response.server_content.model_turn.parts[0].inline_data.mime_type)
    
