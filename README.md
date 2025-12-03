# Scooby Server

Scooby Server is an AI-powered meeting bot that provides real-time transcription and automated summarization for meetings. It uses Recall.ai for meeting integration and LangChain with OpenAI for intelligent summarization.

**Architecture:** FastAPI server managing single tenant – single meeting bot

---

## Features

- ✅ **Real-time Transcription**: Capture live meeting transcripts via Recall.ai webhooks
- ✅ **Intelligent Summarization**: Automatic AI-powered summarization using LangChain and OpenAI
- ✅ **Per-Participant Tracking**: Track individual speakers with timestamps
- ✅ **Dual File Storage**: Save both raw transcripts and summaries
- ✅ **Smart Buffering**: Configurable buffer (7 items or 15 seconds) for efficient summarization
- ✅ **Continuity**: Each summary maintains context from previous summaries
- ✅ **Multi-Platform**: Supports Zoom, Google Meet, Microsoft Teams via Recall.ai

---

## Quick Start

### 1. Environment Setup

Copy the example environment file and configure your API keys:

```bash
cp .env.example .env
```

**Required Environment Variables:**

```env
# Recall.ai (Required - for meeting bot integration)
RECALL_API_KEY=your_recall_api_key_here

# OpenAI (Required - for AI summarization)
OPENAI_API_KEY=your_openai_api_key_here

# Pinecone (Required - for vector search)
PINECONE_API_KEY=your_pinecone_api_key_here

# Neo4j (Required - for knowledge graph)
NEO4J_URI=your_neo4j_uri_here
NEO4J_USER=your_neo4j_username_here
NEO4J_PASSWORD=your_neo4j_password_here
```

**Optional Configuration:**

```env
# Supabase (Optional - for transcript storage)
SUPABASE_URL=your_supabase_url_here
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key_here
SUPABASE_ANON_KEY=your_supabase_anon_key_here

# Summarization Settings (Optional - defaults shown)
SUMMARIZATION_BUFFER_MAX_ITEMS=7
SUMMARIZATION_BUFFER_MAX_SECONDS=15.0
SUMMARIZATION_MODEL=gpt-4o-mini

# Inactivity Monitor (Optional - defaults shown)
SCOOBY_INACTIVITY_POLL_SECONDS=10
SCOOBY_NO_PARTICIPANTS_GRACE_SECONDS=120
SCOOBY_NO_TRANSCRIPTS_GRACE_SECONDS=300
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

**Key Dependencies:**
- `fastapi` - Web framework
- `langchain==0.3.0` - LangChain 1.0 for AI orchestration
- `langchain-openai` - OpenAI integration
- `openai>=1.0.0` - OpenAI API client
- `pinecone` - Vector database
- `neo4j` - Graph database

### 3. Run the Server

**Development mode (with auto-reload):**

```bash
python -m uvicorn app.main:app --reload
```

**Production mode:**

```bash
python -m app.main
```

The server will start on `http://localhost:8000`

---

## How It Works

### Architecture Flow

```
1. Meeting Platform (Zoom/Meet/Teams)
   ↓
2. Recall.ai Bot joins meeting
   ↓
3. Real-time transcription webhook → POST /api/webhook/recall
   ↓
4. Transcript Buffer (collects 7 items OR 15 seconds)
   ↓
5. LangChain Summarization Service (GPT-4o-mini)
   ↓
6. Save to Files:
   - Raw Transcripts: app/transcripts/{org}_{meeting_id}_transcript.txt
   - Summaries: app/summaries/{org}_{meeting_id}_summary.txt
```

### Intelligent Buffering

The system uses a **dual-trigger buffer** for optimal summarization:

- **Item Count Trigger**: Buffer flushes after 7 transcript items
- **Time Trigger**: Buffer flushes after 15 seconds (whichever comes first)

This ensures:
- Efficient API usage (batch processing)
- Timely summaries (not too delayed)
- Contextual summaries (enough content to summarize)

### Summarization with Continuity

Each summary maintains context from previous summaries:

1. **First Summary**: Summarizes initial buffered transcripts
2. **Subsequent Summaries**: Include previous summary as context
3. **Result**: Coherent, connected summaries throughout the meeting

---

## API Endpoints

### Add Scooby Bot

**Endpoint:**

```
POST /add_scooby
```

**Request Body:**

```json
{
  "meeting_url": "string",
  "isTranscript": false,
  "x_org_name": "string",
  "saveTranscript": true
}
```

**Response:**

* If bot successfully added:

```json
{
  "bot_id": "string"
}
```

* If bot already exists:

```json
{
  "message": "Scooby Bot already exists, Please remove and try again"
}
```

**Notes:**

* Single-tenant architecture: only one bot can be active at a time
* Bot automatically handles leave/kick-out scenarios
* Transcripts and summaries are saved locally after meeting ends
* Optional transcript ingestion to external API

**Example cURL:**

```bash
curl -X POST http://localhost:8000/add_scooby \
  -H "Content-Type: application/json" \
  -d '{
        "meeting_url": "https://meet.google.com/abc-defg-hij",
        "isTranscript": false,
        "x_org_name": "acme_corp",
        "saveTranscript": true
      }'
```

### WebSocket Connection

**Endpoint:**

```
WS /ws
```

**Purpose:** Real-time status updates (audio streaming removed)

**Message Format:**

```json
{
  "type": "status",
  "connected": true,
  "bot_type": "scooby"
}
```

### Recall.ai Webhooks

**Bot Status Webhook:**

```
POST /api/webhook/recall/bot-status
```

Handles bot lifecycle events: `joining_call`, `in_call`, `call_ended`, `done`, `fatal`

**Real-time Events Webhook:**

```
POST /api/webhook/recall
```

Handles real-time events:
- `transcript.data` - Transcription segments
- `participant_events.join` - Participant joined
- `participant_events.leave` - Participant left

---

## File Storage

### Output Files

Two files are created per meeting:

**1. Raw Transcripts** (`app/transcripts/`)
```
app/transcripts/{org_name}_{meeting_id}_transcript.txt
```

Format:
```
[2025-12-02 14:30:15] Alice: Let's discuss the project timeline
[2025-12-02 14:30:20] Bob: I think we need two more weeks
[2025-12-02 14:30:25] Charlie: Agreed, that seems reasonable
```

**2. Summaries** (`app/summaries/`)
```
app/summaries/{org_name}_{meeting_id}_summary.txt
```

Format:
```
============================================================
Summary Generated: 2025-12-02 14:30:30
------------------------------------------------------------
Alice, Bob, and Charlie discussed the project timeline. Bob
suggested extending the timeline by two weeks, which Charlie
agreed was reasonable.

============================================================
Summary Generated: 2025-12-02 14:32:45
------------------------------------------------------------
[Next summary continues here with continuity from previous...]
```

---

## Configuration

### Buffer Configuration

Adjust summarization timing via environment variables:

```env
# Maximum transcript items before flush (default: 7)
SUMMARIZATION_BUFFER_MAX_ITEMS=7

# Maximum seconds before flush (default: 15.0)
SUMMARIZATION_BUFFER_MAX_SECONDS=15.0
```

**When to adjust:**
- **More context needed**: Increase `MAX_ITEMS` (e.g., 10-12)
- **Faster summaries**: Decrease `MAX_SECONDS` (e.g., 10.0)
- **Less frequent API calls**: Increase both values

### Model Configuration

Change the LLM model used for summarization:

```env
# Default: gpt-4o-mini (cost-effective)
SUMMARIZATION_MODEL=gpt-4o-mini

# Alternatives:
# SUMMARIZATION_MODEL=gpt-4o (more capable, higher cost)
# SUMMARIZATION_MODEL=gpt-3.5-turbo (faster, lower cost)
```

### Inactivity Monitor

Auto-remove bot when inactive:

```env
# Poll interval (seconds)
SCOOBY_INACTIVITY_POLL_SECONDS=10

# Remove bot if no participants for X seconds
SCOOBY_NO_PARTICIPANTS_GRACE_SECONDS=120

# Remove bot if no transcripts for X seconds
SCOOBY_NO_TRANSCRIPTS_GRACE_SECONDS=300
```

---

## Advanced Features

### Knowledge Base Integration

The bot has access to organizational knowledge via:

**Pinecone Vector Store:**
- Semantic search for "main events"
- Stores high-level meeting summaries
- Embedding model: `llama-text-embed-v2`

**Neo4j Graph Database:**
- Stores fine-grained "sub-events"
- Maintains relationships between events
- Cypher queries for connection retrieval

**Note:** These tools are preserved but not currently integrated into the summarization chain. They remain available for future enhancement.

---

## Recall.ai Integration

### Real-Time Transcription

The bot uses Recall.ai's real-time transcription with low-latency mode:

```python
{
  "meeting_url": "...",
  "recording_config": {
    "transcript": {
      "provider": {
        "recallai_streaming": {
          "mode": "prioritize_low_latency"  # 1-3 second delay
        }
      }
    }
  }
}
```

### Per-Participant Transcription

Each `transcript.data` webhook includes:
- Participant name
- Participant ID, platform, host status
- Words array with timestamps
- Start/end timestamps (relative & absolute)

Example webhook payload:
```json
{
  "event": "transcript.data",
  "data": {
    "data": {
      "participant": {
        "id": 12345,
        "name": "Alice Smith",
        "is_host": false,
        "platform": "desktop"
      },
      "words": [
        {
          "text": "Let's",
          "start_timestamp": {"relative": 0.0},
          "end_timestamp": {"relative": 0.5}
        }
      ]
    }
  }
}
```

**References:**
- [Recall.ai Real-time Transcription](https://docs.recall.ai/docs/bot-real-time-transcription)
- [Recall.ai Webhooks](https://docs.recall.ai/docs/real-time-webhook-endpoints)

---

## Troubleshooting

### Common Issues

**1. OpenAI API Errors**

If summarization fails, the system will:
- Retry up to 3 times with exponential backoff
- Create a fallback summary with participant names and item count
- Log detailed error messages

**2. Buffer Not Flushing**

Check your configuration:
```bash
# Verify environment variables are loaded
python -c "from app.core.config import get_config; print(get_config())"
```

**3. Files Not Created**

Ensure directories exist:
```bash
mkdir -p app/transcripts app/summaries
```

Check permissions:
```bash
ls -la app/transcripts app/summaries
```

**4. Recall.ai Webhook Failures**

- Verify `RECALL_API_KEY` is set correctly
- Check webhook URL is publicly accessible
- Review logs for detailed error messages

---

## Development

### Project Structure

```
scooby/
├── app/
│   ├── api/
│   │   ├── public.py           # Public endpoints
│   │   └── recall.py           # Recall.ai webhooks
│   ├── core/
│   │   ├── config.py           # Configuration (NEW)
│   │   ├── manage_connections.py
│   │   ├── scooby_prompt.py
│   │   ├── tools.py
│   │   └── utils.py
│   ├── service/
│   │   ├── transcript_buffer.py      # Buffer logic (NEW)
│   │   ├── summarization_service.py  # LangChain integration (NEW)
│   │   ├── summary_storage.py        # File I/O (NEW)
│   │   ├── recall_bot.py
│   │   ├── participants.py
│   │   ├── vector_store.py
│   │   ├── graph_store.py
│   │   └── transcript_ingestion.py
│   ├── static/                # Frontend assets
│   ├── templates/             # HTML templates
│   ├── transcripts/           # Raw transcripts output
│   ├── summaries/             # Summaries output (NEW)
│   └── main.py               # Application entry point
├── requirements.txt
├── .env.example              # Environment template (NEW)
└── README.md
```

### Recent Changes (v2.0)

**Removed:**
- ❌ Google Gemini Live API integration
- ❌ Real-time audio streaming via WebSocket
- ❌ "Scooby" wake word detection

**Added:**
- ✅ LangChain 1.0 integration
- ✅ OpenAI GPT-4o-mini for summarization
- ✅ Intelligent transcript buffering
- ✅ Dual file storage system
- ✅ Summary continuity across chunks
- ✅ Configurable buffer and timing

**Benefits:**
- 💰 More cost-effective (GPT-4o-mini vs Gemini Live)
- 📝 Better record-keeping (dual file system)
- 🔧 Easier configuration (environment variables)
- 📊 Automatic processing (no wake word needed)

---

## Contributing

When contributing, ensure:
1. Code follows existing patterns
2. Environment variables are documented
3. Error handling is comprehensive
4. Logs provide useful debugging information

---

## License

[Add your license here]

---

## Support

For issues or questions:
1. Check logs: `tail -f app/logs/scooby.log`
2. Review environment configuration
3. Consult Recall.ai documentation
4. Check OpenAI API status

---

## Changelog

### v2.0.0 (2025-12-02)
- Replaced Gemini Live with LangChain + OpenAI
- Added intelligent transcript buffering
- Implemented dual file storage (transcripts + summaries)
- Added summary continuity feature
- Removed wake word detection (now processes all transcripts)
- Updated configuration system with environment variables

### v1.0.0
- Initial release with Gemini Live integration
- Real-time audio responses
- Basic transcription storage
