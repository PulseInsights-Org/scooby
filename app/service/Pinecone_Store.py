from pinecone import Pinecone
from typing import List, Dict, Any
import logging
from app.core.config import get_config

logger = logging.getLogger(__name__)

class VectoreStore:
    def __init__(self, index_name: str):
        config = get_config()
        self.pc = Pinecone(api_key=config.pinecone_api_key)
        self.index_name = index_name
        self.index = None

    def setup_index(self) -> None:
        if not self.pc.has_index(self.index_name):
            self.pc.create_index_for_model(
                name=self.index_name,
                cloud="aws",
                region="us-east-1",
                embed={
                    "model": "llama-text-embed-v2",
                    "field_map": {"text": "text"},
                },
            )
            logger.info(f"Created Pinecone index for model llama-text-embed-v2: {self.index_name}")

        self.index = self.pc.Index(self.index_name)

    # Backwards-compatible alias if code expects plural name
    def setup_indexes(self) -> None:
        self.setup_index()

    def search_similar_issues(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:

        # Ensure index is initialized
        if self.index is None:  
            self.setup_index()

        try:
            search_response = self.index.search(
                namespace="__default__",
                query={
                    "inputs": {"text": query},
                    "top_k": top_k,
                },
            )

            hits = search_response.get("result", {}).get("hits", [])
            matches: List[Dict[str, Any]] = []

            for hit in hits:
                metadata = hit.get("metadata") or hit.get("fields") or {}
                matches.append({"metadata": metadata})

            return matches

        except Exception as e:
            logger.error(f"Error querying Pinecone index '{self.index_name}': {e}")
            return []
