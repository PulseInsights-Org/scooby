from pinecone import Pinecone
from typing import List, Dict, Any
from langchain_openai import OpenAIEmbeddings
from app.core.config import get_config


class VectoreStore:
    def __init__(self, index_name: str, embedding_model: str = "llama-text-embed-v2"):
        config = get_config()
        self.pc = Pinecone(api_key=config.pinecone_api_key)
        self.index = self.pc.Index(index_name)
        self.embeddings = OpenAIEmbeddings(model=embedding_model, api_key=config.openai_api_key)

    def search_similar_issues(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return top K most similar issue docs based on semantic similarity of the query."""
        query_vector = self.embeddings.embed_query(query)
        res = self.index.query(
            vector=query_vector,
            top_k=top_k,
            include_metadata=True
        )
        return res.get("matches", [])
