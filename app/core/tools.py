from app.service.vector_store import PineconeStore
import os
from app.service.graph_store import Neo4jDriver
from dotenv import load_dotenv
from typing import List
from app.service.recall_bot import RecallBot

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

graph = Neo4jDriver(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
rb = RecallBot()


class GeminiTools():
    
    def __init__(self):
        # Initialize Neo4j only if environment variables are set
        if NEO4J_URI and NEO4J_USER and NEO4J_PASSWORD:
            try:
                self.builder = Neo4jDriver(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
                print("Neo4j connection initialized successfully")
            except Exception as e:
                print(f"Warning: Failed to initialize Neo4j: {e}")
                self.builder = None
        else:
            print("Warning: Neo4J environment variables not set. Graph queries will not work.")
            self.builder = None
            
        # Initialize Pinecone
        pinecone_key = os.getenv("PINECONE_API_KEY", "")
        pinecone_index = os.getenv("PINECONE_INDEX_NAME", "main-events-index")
        if pinecone_key:
            try:
                self.pc = PineconeStore(api_key=pinecone_key, index_name=pinecone_index)
                self.pc.setup_indexes()
                print(f"Pinecone connection initialized successfully with index: {pinecone_index}")
            except Exception as e:
                print(f"Warning: Failed to initialize Pinecone: {e}")
                self.pc = None
        else:
            print("Warning: PINECONE_API_KEY not set. Vector search will not work.")
            self.pc = None
    
    def get_event_connections(self, event_names: List[str]):
    
        cypher = """
        UNWIND $names AS event_name
        MATCH (e:Event {name: event_name})-[r]-(n)
        RETURN event_name AS event,
            n.name AS related_node,
            labels(n)[0] AS node_type,
            type(r) AS relationship_type,
            r.description AS relationship_description
        ORDER BY event_name, related_node
        """
        return self.builder._run(cypher, names=[e for e in event_names])
    
    def pc_retrieval_tool(self, query):
        
        print("fetching from Pinecone")
        results = self.pc.search_main_events(query_text=query)
        return results["results"]

    async def send_chat_message_tool(self, bot_id: str, message: str, to: str = "everyone", pin: bool = False):
        return await rb.send_chat_message(bot_id=bot_id, message=message, to=to, pin=pin)