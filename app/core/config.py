from pydantic import BaseModel
from typing import Literal
import os
from dotenv import load_dotenv

load_dotenv()


class SummarizationConfig(BaseModel):
    """Configuration for transcript summarization system"""

    # Buffer settings
    buffer_max_items: int = int(os.getenv("SUMMARIZATION_BUFFER_MAX_ITEMS", "7"))
    buffer_max_seconds: float = float(os.getenv("SUMMARIZATION_BUFFER_MAX_SECONDS", "15.0"))

    # LLM settings
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    model_name: str = os.getenv("SUMMARIZATION_MODEL", "gpt-4o-mini")
    temperature: float = 0.3  # Lower for consistent summaries
    max_tokens: int = 500  # Summary output limit

    # Vector / search settings
    pinecone_api_key: str = os.getenv("PINECONE_API_KEY", "")
    pinecone_index_name: str = os.getenv("PINECONE_ISSUES_INDEX_NAME", "")

    # Storage settings
    summaries_dir: str = "summaries"
    transcripts_dir: str = "transcripts"

    # Summarization behavior
    include_timestamps: bool = True
    include_speaker_names: bool = True
    continuity_enabled: bool = True  # Include previous summary in context

    # File naming
    summary_file_suffix: str = "_summary.txt"
    transcript_file_suffix: str = "_transcript.txt"
    events_file_suffix: str = "_events.txt"


def get_config() -> SummarizationConfig:
    """Get summarization configuration singleton"""
    return SummarizationConfig()
