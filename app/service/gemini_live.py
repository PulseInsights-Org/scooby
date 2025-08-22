from google import genai
from app.core.manage_connections import ConnectionManager
import base64
from app.core.tools import GeminiTools
from google.genai.types import FunctionDeclaration
from google.genai import types 
from app.core.scooby_prompt import prompt

class GeminiLive():
    
    def __init__(self, api_key = "AIzaSyBUjH-PkLSZzyDxFXeTlTw9s8PaZq2nNPc", connection_manager: ConnectionManager = None):
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-live-2.5-flash-preview"
        self.tools = []
        self.define_tools()
        self.config = {
            "response_modalities": ["AUDIO"],
            "temperature": 0,
            "tools" : self.tools,
            "system_instruction": prompt()
        }
        self.connection_manager = connection_manager
        self.tool_executor = GeminiTools()
    
    async def _async_enumerate(self, aiterable):
        n = 0
        async for item in aiterable:
            yield n, item
            n += 1
    
    # 2. Add coversation history
    # 3. voice, temp, prompt, transcription etc -> slaient features

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
        
        self.tools = [{"function_declarations": [pc_retrieval_tool, connections_retrieval_tool]}]
    
    async def connect_to_gemini(self, text):
        async with self.client.aio.live.connect(
            model = self.model,
            config=self.config,
        ) as connection : 
            message = text
            await connection.send_client_content(
                turns={"role": "user", "parts": [{"text": message}]}, turn_complete=True
            )
            
            turn = connection.receive()
            async for n, response in self._async_enumerate(turn):
                if response.server_content:
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
                elif response.tool_call:
                    try:
                        function_responses = []
                        for fc in response.tool_call.function_calls:
                            
                            function_name = fc.name
                            function_args = fc.args
                            print("function called by gemini", function_name)
                            
                            try:
                                if function_name == "connections_retrieval_tool":
                                    event = function_args.get("event_names")
                                    data = self.tool_executor.get_event_connections(event)
                                    
                                elif function_name == "pc_retrieval_tool":
                                    query = function_args.get("query")
                                    data = self.tool_executor.pc_retrieval_tool(query)
                                    
                                    
                                else:
                                    data = {"error": f"Unknown function: {function_name}"}
                                    
                                function_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"result": data}
                                )
                                
                                function_responses.append(function_response)
                            except Exception as tool_error:
                                print(f"Error executing tool {function_name}: {tool_error}")
                                error_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"error": str(tool_error)}
                                )
                                function_responses.append(error_response)
                        
                        if function_responses:
                            print("sending gemini function response...")
                            await connection.send_tool_response(function_responses=function_responses)
                    except Exception as e:
                        print(f"Error processing tool calls: {e}")
                if n == 0:
                    try:
                        if (response.server_content and 
                            response.server_content.model_turn and 
                            response.server_content.model_turn.parts and 
                            len(response.server_content.model_turn.parts) > 0 and
                            response.server_content.model_turn.parts[0].inline_data):
                            print(response.server_content.model_turn.parts[0].inline_data.mime_type)
                        else:
                            print("No inline data available in response")
                    except AttributeError as e:
                        print(f"Error accessing response data: {e}")
    
