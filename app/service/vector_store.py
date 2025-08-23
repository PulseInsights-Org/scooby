from pinecone import Pinecone
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class PineconeStore():
    def __init__(self, api_key, index_name="main-events-index"):
        self.pc = Pinecone(api_key=api_key)
        self.index_name = index_name
    
    def setup_indexes(self):
        if not self.pc.has_index(self.index_name):
            self.pc.create_index_for_model(
                name=self.index_name,
                cloud="aws",
                region="us-east-1",
                embed={
                    "model": "llama-text-embed-v2",
                    "field_map": {"text": "text"}
                }
            )
            logger.info(f"Created index: {self.index_name}")
            
        self.index = self.pc.Index(self.index_name)
    
    def search_main_events(self, query_text: str, top_k: int = 5, filter_dict: Optional[Dict] = None):
        
        try:
            query_response = self.index.search(
                namespace=self.index_name,   
                query={
                    "inputs": {"text": query_text},
                    "top_k": top_k,
                    "filter": filter_dict or {}
                },
                fields=["title", "main_event", "sub_events", "summary", "node_id"]
            )
            
            results = []
            for hit in query_response["result"]["hits"]:
                fields = hit.get("fields", {})
                results.append({
                    "id": hit.get("_id"),
                    "score": hit.get("_score"),
                    "main_event": fields.get("main_event", ""),
                    "sub_events": fields.get("sub_events", []),
                    "summary": fields.get("summary", ""),
                    "title": fields.get("title", "")
                })

            return {
                "status": "success",
                "results": results,
                "total_results": len(results)
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "results": []
            }