from app.service.vector_store import PineconeStore
import os
from app.service.graph_store import Neo4jDriver
from dotenv import load_dotenv
from typing import List
from app.service.recall_bot import RecallBot
import logging

logger = logging.getLogger(__name__)

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

graph = Neo4jDriver(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
rb = RecallBot()


class GeminiTools():
    
    def __init__(self):
        self.builder = Neo4jDriver(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
        self.pc =  PineconeStore(api_key=os.getenv("PINECONE_API_KEY", ""), index_name="idx-pulse-dev")
        self.pc.setup_indexes()
    
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
        logger.info("fetching from Pinecone")
        results = self.pc.search_main_events(query_text=query)
        return results["results"]

    async def send_chat_message_tool(self, bot_id: str, message: str, to: str = "everyone", pin: bool = False):
        return await rb.send_chat_message(bot_id=bot_id, message=message, to=to, pin=pin)