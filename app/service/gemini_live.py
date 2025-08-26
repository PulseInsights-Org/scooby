from google import genai
from app.core.manage_connections import ConnectionManager
import base64
from app.core.tools import GeminiTools
from google.genai.types import FunctionDeclaration
from google.genai import types 
from app.core.scooby_prompt import prompt
import logging

logger = logging.getLogger(__name__)


class GeminiLive():
    
    def __init__(self, api_key = "AIzaSyBUjH-PkLSZzyDxFXeTlTw9s8PaZq2nNPc", connection_manager: ConnectionManager = None, transcript_writer = None):
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-live-2.5-flash-preview"
        self.tools = []
        self.define_tools()
        self.config = {
            "response_modalities": ["AUDIO"],
            "output_audio_transcription": {},
            "temperature": 0.3,
            "tools" : self.tools,
            "system_instruction": prompt(),
        }
        self.connection_manager = connection_manager
        self.tool_executor = GeminiTools()
        self.conversation_history = []
        self.chat_history = []
        self.current_transcription = ""
        self.bot_id = None
        self.participants = []
        self.tw = transcript_writer
    
    async def _async_enumerate(self, aiterable):
        n = 0
        async for item in aiterable:
            yield n, item
            n += 1
    
    def define_tools(self):
        connections_retrieval_tool = FunctionDeclaration(
            name="connections_retrieval_tool",
            description="Fetch all the related information of one or many events",
            parameters={
                "type": "object",
                "properties": {
                    "event_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of event names of which connections should be fetched"
                    }
                },
                "required": ["event_names"],
            }
        )
        
        pc_retrieval_tool = FunctionDeclaration(
            name="pc_retrieval_tool",
            description="Fetch top relevant main events from Pinecone vector store using query text",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The natural language query to search relevant main events"
                    }
                },
                "required": ["query"],
            }
        )

        send_chat_message_tool = FunctionDeclaration(
            name="send_chat_message_tool",
            description="Send a chat message to the current Recall meeting via the active bot.",
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message text to send to the meeting chat"
                    },
                    "to": {
                        "type": "string",
                        "description": "Recipient scope, e.g., 'everyone'",
                        "default": "everyone"
                    },
                    "pin": {
                        "type": "boolean",
                        "description": "Whether to pin the message in the meeting UI",
                        "default": False
                    }
                },
                "required": ["message"],
            }
        )

        get_current_participants_tool = FunctionDeclaration(
            name="get_current_participants",
            description="Gets all participants who are currently in the meeting (status == 'joined').",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            }
        )

        get_all_joined_participants_tool = FunctionDeclaration(
            name="get_all_joined_participants",
            description="Gets all participants who have joined the meeting, including those who later left.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            }
        )
        
        self.tools = [{"function_declarations": [
            pc_retrieval_tool,
            connections_retrieval_tool,
            send_chat_message_tool,
            get_current_participants_tool,
            get_all_joined_participants_tool,
        ]}]
    
    async def connect_to_gemini(self, text):
        async with self.client.aio.live.connect(
            model = self.model,
            config=self.config,
        ) as connection : 
            recent_turns = self.chat_history[-5:] if len(self.chat_history) > 5 else self.chat_history
            history_lines = []
            for t in recent_turns:
                try:
                    role = t.get("role", "user")
                    parts = t.get("parts", [])
                    content_text = parts[0].get("text") if parts and isinstance(parts[0], dict) else ""
                    history_lines.append(f"{role}: {content_text}")
                except Exception:
                    pass

            composed = ""
            if history_lines:
                composed = "Conversation history:\n" + "\n".join(history_lines) + "\n\n"
            composed += f"Question: {text}"
            

            await connection.send_client_content(
                turns={"role": "user", "parts": [{"text": composed}]}, turn_complete=True
            )

            current_turn = {"role": "user", "parts": [{"text": text}]}
            self.chat_history.append(current_turn)
            if len(self.chat_history) > 5:
                self.chat_history = self.chat_history[-5:]
            
            turn = connection.receive()
            async for n, response in self._async_enumerate(turn):
                
                if response.server_content:
                    transcription = getattr(response.server_content, "output_transcription", None)
                    
                    if transcription:
                        transcribed_text = getattr(transcription, "text", None)
                        if transcribed_text:
                            self.current_transcription += transcribed_text
                    
                    if response.data is not None and self.connection_manager is not None:
                        try:
                            encoded = base64.b64encode(response.data).decode("ascii")
                        except Exception as encode_err:
                            logger.exception(f"Error base64-encoding audio chunk: {encode_err}")
                            encoded = None
                            
                        if encoded:
                            logger.debug("sending audio")
                            await self.connection_manager.send_to_all({
                                "type": "audio",
                                "data": encoded,
                                "bot_type": "scooby"
                            })
                elif response.tool_call:
                    try:
                        function_responses = []
                        for fc in response.tool_call.function_calls:
                            
                            function_name = fc.name
                            function_args = fc.args
                            logger.info(f"function called by gemini: {function_name}")
                            
                            try:
                                if function_name == "connections_retrieval_tool":
                                    event = function_args.get("event_names")
                                    data = self.tool_executor.get_event_connections(event)
                                    
                                elif function_name == "pc_retrieval_tool":
                                    query = function_args.get("query")
                                    data = self.tool_executor.pc_retrieval_tool(query)
                                    
                                elif function_name == "send_chat_message_tool":
                                    if not self.bot_id:
                                        raise RuntimeError("No active bot_id set on model; cannot send chat message")
                                    message = function_args.get("message")
                                    to = function_args.get("to", "everyone")
                                    pin = function_args.get("pin", False)
                                    data = await self.tool_executor.send_chat_message_tool(self.bot_id, message, to, pin)
                                
                                elif function_name == "get_current_participants":
                                    data = [p for p in (self.participants or []) if p.get("status") == "joined"]
                                
                                elif function_name == "get_all_joined_participants":
                                    data = self.participants or []
                                
                                else:
                                    data = {"error": f"Unknown function: {function_name}"}
                                
                                logger.debug(f"Function result for {function_name}: {data}")
                                    
                                function_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"result": data}
                                )
                                
                                function_responses.append(function_response)
                            
                            except Exception as tool_error:
                                logger.exception(f"Error executing tool {function_name}: {tool_error}")
                                error_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"error": str(tool_error)}
                                )
                                function_responses.append(error_response)
                        
                        if function_responses:
                            logger.debug("sending gemini function response...")
                            await connection.send_tool_response(function_responses=function_responses)
                    except Exception as e:
                        logger.exception(f"Error processing tool calls: {e}")
                        
                if n == 0:
                    try:
                        if (response.server_content and 
                            response.server_content.model_turn and 
                            response.server_content.model_turn.parts and 
                            len(response.server_content.model_turn.parts) > 0 and
                            response.server_content.model_turn.parts[0].inline_data):
                            logger.debug(response.server_content.model_turn.parts[0].inline_data.mime_type)
                        else:
                            logger.debug("No inline data available in response")
                    except AttributeError as e:
                        logger.exception(f"Error accessing response data: {e}")
            
            
                turn_complete = bool(getattr(getattr(response, 'server_content', None), 'turn_complete', False))
                
                if turn_complete:
                    
                    if self.current_transcription and self.current_transcription.strip():
                        final_text = self.current_transcription.strip()
                        logger.info(f"[Scooby]: {final_text}")
                        self.tw.save_line(speaker="Scooby", text=final_text)
                        self.conversation_history.append({
                            "role": "model",
                            "content": final_text,
                            "type": "audio_response"
                        })
                        
                        self.chat_history.append({
                            "role": "model",
                            "parts": [{"text": final_text}]
                        })
                        
                        if len(self.chat_history) > 5:
                            self.chat_history = self.chat_history[-5:]
                    self.current_transcription = ""
                    
            if self.current_transcription and self.current_transcription.strip():
                final_text = self.current_transcription.strip()
                logger.info(f"[Scooby]: {final_text}")
                self.conversation_history.append({
                    "role": "model",
                    "content": final_text,
                    "type": "audio_response"
                })
                
                self.chat_history.append({
                    "role": "model",
                    "parts": [{"text": final_text}]
                })
                
                if len(self.chat_history) > 5:
                    self.chat_history = self.chat_history[-5:]
                    
                self.current_transcription = ""
    
