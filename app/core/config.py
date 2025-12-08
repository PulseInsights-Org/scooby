from pydantic import BaseModel
from typing import Literal
import os
from dotenv import load_dotenv

load_dotenv()

class SummarizationConfig(BaseModel):
    """Configuration for transcript summarization system"""

    # Public URL settings (for webhooks and websockets)
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "")
    
    # Recall.ai settings
    recall_api_key: str = os.getenv("RECALL_API_KEY", "")

    # GoCobalt settings (Slack send message workflow)
    cobalt_api_key: str = os.getenv("COBALT_API_KEY", "")

    # Buffer settings
    buffer_max_items: int = int(os.getenv("SUMMARIZATION_BUFFER_MAX_ITEMS", "7"))
    buffer_max_seconds: float = float(os.getenv("SUMMARIZATION_BUFFER_MAX_SECONDS", "15.0"))

    # LLM settings
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    model_name: str = os.getenv("SUMMARIZATION_MODEL", "gpt-4o-mini")
    temperature: float = 0.3  
    max_tokens: int = 500 

    # AWS settings (for S3 access)
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    aws_region: str = os.getenv("AWS_REGION", "")

    # Vector / search settings
    pinecone_api_key: str = os.getenv("PINECONE_API_KEY", "")
    pinecone_index_name: str = os.getenv("PINECONE_ISSUES_INDEX_NAME", "")

    # Supabase settings (for transcript + screenshare metadata storage)
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")

    # Screenshare metadata table name (constant, not from env)
    screenshare_metadata_table: str = "screenshare_frames"

    # Screenshare S3 configuration
    screenshare_s3_bucket: str = os.getenv("SCREENSHARE_S3_BUCKET", "")
    screenshare_s3_prefix: str = "screenshares/"

    # Storage settings
    summaries_dir: str = "summaries"
    transcripts_dir: str = "transcripts"

    # Summarization behavior
    include_timestamps: bool = True
    include_speaker_names: bool = True
    continuity_enabled: bool = True  

    # File naming
    summary_file_suffix: str = "_summary.txt"
    transcript_file_suffix: str = "_transcript.txt"
    events_file_suffix: str = "_events.txt"


def get_config() -> SummarizationConfig:
    """Get summarization configuration singleton"""
    return SummarizationConfig()
