# Scooby Server - Complete Architecture & Working Guide

## 📋 Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Core Components](#core-components)
4. [Data Flow](#data-flow)
5. [Key Features](#key-features)
6. [File Structure](#file-structure)
7. [API Endpoints](#api-endpoints)
8. [Webhook System](#webhook-system)
9. [Storage Systems](#storage-systems)
10. [Configuration](#configuration)
11. [Development Workflow](#development-workflow)

---

## Overview

**Scooby Server** is an AI-powered meeting bot that provides:
- Real-time transcription via Recall.ai
- Intelligent event extraction and summarization using LangChain + OpenAI
- Screenshare capture and storage
- Knowledge base integration (Pinecone + Neo4j)
- Automated meeting minutes generation

**Architecture Model:** Single-tenant, single-meeting bot (one active bot at a time)

**Tech Stack:**
- **Backend:** FastAPI (Python)
- **AI/ML:** LangChain 0.3.0, OpenAI GPT-4o-mini
- **Meeting Integration:** Recall.ai
- **Vector DB:** Pinecone (for semantic search)
- **Graph DB:** Neo4j (for relationship mapping)
- **Storage:** Supabase (metadata), AWS S3 (screenshares), Redis (buffering)

---

## Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Meeting Platform                              │
│              (Zoom / Google Meet / Teams)                        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Recall.ai Bot                               │
│  • Joins meeting as participant                                  │
│  • Captures audio/video/screenshare                             │
│  • Sends real-time events via webhooks/websockets               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Scooby Server (FastAPI)                       │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Webhook    │  │  WebSocket   │  │  Public API  │          │
│  │   Handlers   │  │   Handlers   │  │  Endpoints   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                  │                  │                   │
│         └──────────────────┼──────────────────┘                  │
│                            │                                      │
│  ┌─────────────────────────┴─────────────────────────┐          │
│  │           Core Processing Pipeline                 │          │
│  │                                                     │          │
│  │  1. Transcript Buffer (7 items / 15 seconds)      │          │
│  │  2. Summarization Service (LangChain + GPT)       │          │
│  │  3. Event Extraction                               │          │
│  │  4. Knowledge Base Search (Pinecone/Neo4j)        │          │
│  │  5. Storage (Files + Supabase)                    │          │
│  └───────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Storage Layer                                 │
│                                                                   │
│  • Local Files: transcripts/*.txt, summaries/*.txt              │
│  • Supabase: screenshare metadata                               │
│  • S3: screenshare images                                       │
│  • Redis: screenshare frame buffer                              │
│  • Pinecone: vector embeddings                                  │
│  • Neo4j: knowledge graph                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. **API Layer** (`app/api/`)

#### `public.py`
- **Purpose:** Public-facing endpoints for bot management
- **Key Endpoints:**
  - `GET /` - Serves bot HTML interface
  - `POST /add_scooby` - Creates and adds bot to meeting
- **Request Model:**
  ```python
  {
    "meeting_url": str,        # Zoom/Meet/Teams URL
    "isTranscript": bool,      # Enable transcription
    "x_org_name": str,         # Organization identifier
    "saveTranscript": bool     # Save transcript to file
  }
  ```

#### `recall.py`
- **Purpose:** Handles all Recall.ai webhooks and WebSocket connections
- **Key Functions:**
  - `add_bot()` - Creates bot and initializes state
  - `recall_webhook()` - Processes real-time transcription events
  - `recall_bot_status_webhook()` - Handles bot lifecycle events
  - `recall_realtime_websocket()` - Processes screenshare frames
  - `_process_buffer_and_summarize()` - Main processing pipeline

**Global State Management:**
```python
current_bot_id = None              # Active bot ID
current_meeting_url = None         # Meeting URL
transcripts_enabled = False        # Transcription flag
current_x_org_name = None          # Organization name
transcript_buffer = None           # Buffer instance
summary_storage = None             # Storage instance
```

### 2. **Core Layer** (`app/core/`)

#### `config.py`
- **Purpose:** Centralized configuration management
- **Key Settings:**
  - Buffer configuration (max items, max seconds)
  - LLM settings (model, temperature, max tokens)
  - AWS/Pinecone/Supabase credentials
  - File naming conventions

#### `utils.py`
- **TranscriptWriter:** Writes transcript lines to disk
- **BotContext:** Manages bot state and lifecycle
- **InactivityMonitor:** Auto-removes bot on inactivity
  - Triggers: No participants (120s) OR no transcripts (300s)
  - Polls every 10 seconds

#### `manage_connections.py`
- **ConnectionManager:** Manages WebSocket connections for real-time updates

### 3. **Service Layer** (`app/service/`)

#### `recall_bot.py`
- **RecallBot Class:** Interfaces with Recall.ai API
- **Methods:**
  - `add_bots()` - Creates bot with configuration
  - `handle_bot_removal()` - Removes bot from meeting
  - `send_chat_message()` - Sends chat to meeting

**Bot Configuration:**
```python
{
  "recording_config": {
    "video_separate_png": {},
    "video_mixed_layout": "gallery_view_v2",
    "realtime_endpoints": [
      {
        "type": "webhook",
        "url": "https://your-domain/api/webhook/recall",
        "events": ["transcript.data", "participant_events.join", "participant_events.leave"]
      },
      {
        "type": "websocket",
        "url": "wss://your-domain/api/ws/recall-realtime",
        "events": ["participant_events.screenshare_on", "participant_events.screenshare_off", "video_separate_png.data"]
      }
    ],
    "transcript": {
      "provider": {
        "meeting_captions": {}  # Uses platform's native captions
      }
    }
  }
}
```

#### `transcript_buffer.py`
- **TranscriptBuffer Class:** Manages buffering logic
- **Dual-Trigger System:**
  - **Item Count:** Flushes after 7 items (configurable)
  - **Time-Based:** Flushes after 15 seconds (configurable)
- **TranscriptItem Model:**
  ```python
  {
    "speaker": str,
    "text": str,
    "timestamp": datetime,
    "start_time": float,  # Relative timestamp from Recall.ai
    "end_time": float
  }
  ```

#### `summarization_service.py`
- **SummarizationService Class:** LangChain-based AI processing
- **Key Features:**
  - Event extraction with categorization
  - Global summary generation (MOM style)
  - Knowledge base integration
  - Screenshare frame retrieval

**Event Types:**
1. **issue-related:** Technical issues, blockers, logs
2. **MoM-event:** References to previous meeting context
3. **general-event:** Everything else

**Output Structure:**
```python
{
  "events": [
    {
      "timestamp": "00:15-00:18",
      "event": "Discussed API rate limiting issue",
      "person": "Alice",
      "event_type": "issue-related"
    }
  ],
  "summary": "Complete meeting summary in MOM format...",
  "suggestion": "Optional AI-generated suggestion based on knowledge base"
}
```

**LangChain Tools:**
1. `search_meeting_knowledge_base()` - Searches Pinecone/Neo4j
2. `get_screenshare_frames_by_time()` - Retrieves screenshare frames

#### `summary_storage.py`
- **SummaryStorage Class:** Manages file I/O for meeting artifacts
- **Three Files Per Meeting:**
  1. `{org}_{meeting_id}_transcript.txt` - Raw transcripts (append-only)
  2. `{org}_{meeting_id}_events.txt` - Event timeline (append-only)
  3. `{org}_{meeting_id}_summary.txt` - Global summary (replace)

**Transcript Format:**
```
[00:15-00:18] Alice: Let's discuss the API issue
[00:19-00:22] Bob: I think it's a rate limiting problem
```

**Events Format:**
```
[00:15-00:18] [Discussed API rate limiting issue] [by Alice]
[00:19-00:22] [Suggested rate limiter implementation] [by Bob]
```

#### `participants.py`
- **ParticipantsManager Class:** Tracks meeting participants
- **Participant Model:**
  ```python
  {
    "id": str,
    "name": str,
    "is_host": bool,
    "platform": str,
    "extra_data": dict,
    "status": "joined" | "left"
  }
  ```

#### `screenshare_buffer.py`
- **ScreenshareRedisBuffer Class:** Redis-backed frame buffer
- **Key Pattern:** `screenshare:{bot_id}:{participant_id}`
- **Frame Data:**
  ```python
  {
    "org_name": str,
    "bot_id": str,
    "participant_id": str,
    "participant_name": str,
    "timestamp_absolute": str,
    "timestamp_relative": float,
    "hash": str,              # Perceptual hash for deduplication
    "image_base64": str       # Base64-encoded PNG
  }
  ```
- **Buffer Size:** 100 frames per participant (configurable)
- **TTL:** 3600 seconds (1 hour)

#### `screenshare_s3.py`
- **ScreenshareS3 Class:** Uploads frames to S3
- **S3 Key Format:** `screenshares/{org_name}/{bot_id}/{participant_id}/{timestamp}_{hash}.png`
- **Also stores metadata in Supabase**

#### `screenshare_metadata_store.py`
- **ScreenshareMetadataStore Class:** Supabase metadata storage
- **Table:** `screenshare_frames`
- **Schema:**
  ```sql
  CREATE TABLE screenshare_frames (
    org_name TEXT,
    bot_id TEXT,
    participant_id TEXT,
    participant_name TEXT,
    timestamp_absolute TIMESTAMPTZ,
    timestamp_relative DOUBLE PRECISION,
    img_hash TEXT,
    s3_bucket TEXT,
    s3_key TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```

#### `transcript_ingestion.py`
- **TranscriptIngestion Class:** Uploads transcripts to external API
- **Pipeline:**
  1. `init_intake()` - Initialize intake session
  2. `upload_file()` - Upload transcript file
  3. `get_intake_status()` - Check upload status
  4. `finalize_intake()` - Finalize processing
- **Base URL:** `https://dev.pulse-api.getpulseinsights.ai`

#### `vector_store.py` & `Pinecone_Store.py`
- **Purpose:** Semantic search for meeting context
- **Embedding Model:** `llama-text-embed-v2`
- **Use Case:** Search for similar issues/topics from past meetings

#### `graph_store.py`
- **Purpose:** Neo4j graph database for relationship mapping
- **Use Case:** Track connections between events, people, topics

---

## Data Flow

### 1. **Bot Creation Flow**

```
User → POST /add_scooby
  ↓
add_bot() function
  ↓
RecallBot.add_bots() → Recall.ai API
  ↓
Initialize:
  • current_bot_id
  • transcript_buffer
  • summary_storage
  • inactivity_monitor
  ↓
Bot joins meeting
```

### 2. **Transcription Processing Flow**

```
Recall.ai → POST /api/webhook/recall (event: transcript.data)
  ↓
Extract: speaker, text, start_time, end_time
  ↓
Duplicate check (segment key: start:end:speaker)
  ↓
Save to files:
  • summary_storage.save_transcript_line()
  • transcript_writer.save_line()
  ↓
Add to transcript_buffer
  ↓
Check flush conditions:
  • 7 items OR 15 seconds
  ↓
If flush needed → _process_buffer_and_summarize()
  ↓
SummarizationService.process_segment()
  ↓
LangChain chain execution:
  1. Extract events
  2. Search knowledge base (optional)
  3. Generate summary
  4. Generate suggestion (optional)
  ↓
Save results:
  • summary_storage.append_events()
  • summary_storage.replace_summary()
```

### 3. **Screenshare Processing Flow**

```
Recall.ai → WebSocket /api/ws/recall-realtime (event: video_separate_png.data)
  ↓
Check: type == "screenshare" AND participant in active_screensharers
  ↓
FPS downsampling (1 frame every 2 seconds)
  ↓
Perceptual hash deduplication (imagehash.phash)
  ↓
Parallel storage:
  ├─→ screenshare_buffer.push_frame() → Redis
  └─→ screenshare_s3.push_frame() → S3 + Supabase metadata
```

### 4. **Bot Lifecycle Flow**

```
Bot Status Events (POST /api/webhook/recall/bot-status):

joining_call → Log "Bot joining"
  ↓
in_call → Log "Bot joined"
  ↓
in_call_recording → Log "Bot recording"
  ↓
call_ended / done / fatal:
  1. Flush remaining buffer
  2. Process final transcripts
  3. Ingest transcript to external API
  4. Delete local transcript file
  5. Reset participants
  6. Stop inactivity monitor
  7. Clear global state
```

### 5. **Inactivity Monitoring Flow**

```
InactivityMonitor.start(bot_id)
  ↓
Background task polls every 10 seconds
  ↓
Check conditions:
  • No participants for 120s?
  • No transcripts for 300s?
  ↓
If either condition met:
  1. Call RecallBot.handle_bot_removal()
  2. Save status to transcript
  3. Reset participants
  4. Clear global state
```

---

## Key Features

### 1. **Intelligent Buffering**
- **Purpose:** Batch transcripts for efficient API usage
- **Triggers:** 7 items OR 15 seconds (whichever comes first)
- **Benefits:**
  - Reduces API calls
  - Provides enough context for summarization
  - Ensures timely processing

### 2. **Summary Continuity**
- **Mechanism:** Each summary includes previous summary as context
- **Result:** Coherent, connected summaries throughout meeting
- **Implementation:**
  ```python
  current_summary = await summary_storage.get_current_summary()
  result = await summarization_service.process_segment(items, current_summary)
  ```

### 3. **Event Categorization**
- **issue-related:** Triggers Pinecone search for similar issues
- **MoM-event:** Triggers Neo4j search for previous meeting context
- **general-event:** No additional search

### 4. **Screenshare Deduplication**
- **Method:** Perceptual hashing (imagehash.phash)
- **Benefits:** Reduces storage costs, avoids duplicate frames
- **FPS Control:** ~1 frame every 2 seconds per participant

### 5. **Automatic Cleanup**
- **Inactivity Detection:** Removes bot when inactive
- **Transcript Ingestion:** Uploads to external API after meeting
- **File Deletion:** Removes local transcript after successful upload

---

## File Structure

```
scooby/
├── .env                          # Environment variables (gitignored)
├── .env.example                  # Environment template
├── requirements.txt              # Python dependencies
├── README.md                     # User documentation
│
├── app/
│   ├── main.py                   # FastAPI application entry point
│   │
│   ├── api/                      # API endpoints
│   │   ├── public.py             # Public endpoints (/add_scooby)
│   │   └── recall.py             # Recall.ai webhooks & WebSockets
│   │
│   ├── core/                     # Core utilities
│   │   ├── config.py             # Configuration management
│   │   ├── utils.py              # TranscriptWriter, BotContext, InactivityMonitor
│   │   └── manage_connections.py # WebSocket connection manager
│   │
│   ├── service/                  # Business logic
│   │   ├── recall_bot.py         # Recall.ai API client
│   │   ├── transcript_buffer.py  # Transcript buffering logic
│   │   ├── summarization_service.py  # LangChain + OpenAI integration
│   │   ├── summary_storage.py    # File I/O for transcripts/summaries
│   │   ├── participants.py       # Participant management
│   │   ├── transcript_ingestion.py  # External API upload
│   │   ├── screenshare_buffer.py # Redis frame buffer
│   │   ├── screenshare_s3.py     # S3 upload
│   │   ├── screenshare_metadata_store.py  # Supabase metadata
│   │   ├── screenshare_storage.py  # Screenshare orchestration
│   │   ├── vector_store.py       # Pinecone integration
│   │   ├── Pinecone_Store.py     # Pinecone client
│   │   └── graph_store.py        # Neo4j integration
│   │
│   ├── static/                   # Frontend assets
│   ├── templates/                # HTML templates
│   │   └── bot.html              # Bot interface
│   │
│   ├── transcripts/              # Raw transcript output
│   │   └── Scooby_{org}_{id}.txt
│   │
│   └── summaries/                # Summary output
│       ├── {org}_{meeting_id}_transcript.txt
│       ├── {org}_{meeting_id}_events.txt
│       └── {org}_{meeting_id}_summary.txt
│
└── .venv/                        # Virtual environment
```

---

## API Endpoints

### Public Endpoints

#### `GET /`
- **Purpose:** Serve bot HTML interface
- **Response:** HTML page

#### `POST /add_scooby`
- **Purpose:** Create and add bot to meeting
- **Request:**
  ```json
  {
    "meeting_url": "https://meet.google.com/abc-defg-hij",
    "isTranscript": false,
    "x_org_name": "acme_corp",
    "saveTranscript": true
  }
  ```
- **Response (Success):**
  ```json
  {
    "bot_id": "abc123xyz"
  }
  ```
- **Response (Bot Exists):**
  ```json
  {
    "message": "Scooby Bot already exists, Please remove and try again"
  }
  ```

### WebSocket Endpoints

#### `WS /ws`
- **Purpose:** Real-time status updates
- **Message Format:**
  ```json
  {
    "type": "status",
    "connected": true,
    "bot_type": "scooby"
  }
  ```

#### `WS /api/ws/recall-realtime`
- **Purpose:** Receive screenshare frames from Recall.ai
- **Events:**
  - `participant_events.screenshare_on`
  - `participant_events.screenshare_off`
  - `video_separate_png.data`

### Webhook Endpoints

#### `POST /api/webhook/recall/bot-status`
- **Purpose:** Bot lifecycle events
- **Events:**
  - `joining_call` - Bot joining meeting
  - `in_call` - Bot in meeting
  - `in_call_recording` - Bot recording
  - `call_ended` - Call ended
  - `done` - Bot finished
  - `fatal` - Bot error

#### `POST /api/webhook/recall`
- **Purpose:** Real-time transcription and participant events
- **Events:**
  - `transcript.data` - Transcription segment
  - `participant_events.join` - Participant joined
  - `participant_events.leave` - Participant left

---

## Webhook System

### Recall.ai Webhook Configuration

**Webhook URL:** `https://your-domain/api/webhook/recall`

**Events:**
1. **transcript.data**
   ```json
   {
     "event": "transcript.data",
     "data": {
       "bot": {"id": "bot123"},
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

2. **participant_events.join**
   ```json
   {
     "event": "participant_events.join",
     "data": {
       "bot": {"id": "bot123"},
       "data": {
         "action": "join",
         "participant": {
           "id": 12345,
           "name": "Alice Smith",
           "is_host": false,
           "platform": "desktop"
         }
       }
     }
   }
   ```

3. **participant_events.leave**
   ```json
   {
     "event": "participant_events.leave",
     "data": {
       "bot": {"id": "bot123"},
       "data": {
         "participant": {
           "id": 12345,
           "name": "Alice Smith"
         }
       }
     }
   }
   ```

---

## Storage Systems

### 1. **Local File Storage**

**Location:** `app/transcripts/` and `app/summaries/`

**Files:**
- `Scooby_{org}_{id}.txt` - Legacy transcript format
- `{org}_{meeting_id}_transcript.txt` - Timestamped transcripts
- `{org}_{meeting_id}_events.txt` - Event timeline
- `{org}_{meeting_id}_summary.txt` - Global summary

### 2. **Redis (Screenshare Buffer)**

**Purpose:** Temporary frame buffer
**Key Pattern:** `screenshare:{bot_id}:{participant_id}`
**Data:** JSON array of frame objects
**TTL:** 3600 seconds

### 3. **AWS S3 (Screenshare Storage)**

**Bucket:** `scooby-s3-screen-capture` (configurable)
**Key Format:** `screenshares/{org}/{bot_id}/{participant_id}/{timestamp}_{hash}.png`
**Content-Type:** `image/png`

### 4. **Supabase (Metadata)**

**Table:** `screenshare_frames`
**Purpose:** Queryable metadata for screenshare frames
**Indexes:** participant_name, timestamp_relative

### 5. **Pinecone (Vector Search)**

**Purpose:** Semantic search for issues/topics
**Embedding Model:** `llama-text-embed-v2`
**Index:** Configurable via `PINECONE_ISSUES_INDEX_NAME`

### 6. **Neo4j (Knowledge Graph)**

**Purpose:** Relationship mapping between events
**Use Case:** Track connections between people, topics, decisions

---

## Configuration

### Required Environment Variables

```bash
# Recall.ai
RECALL_API_KEY=your_recall_api_key

# OpenAI
OPENAI_API_KEY=your_openai_api_key

# Pinecone
PINECONE_API_KEY=your_pinecone_api_key

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# AWS (for S3)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=ap-south-1
```

### Optional Environment Variables

```bash
# Supabase
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
SUPABASE_ANON_KEY=your_anon_key

# Summarization
SUMMARIZATION_BUFFER_MAX_ITEMS=7
SUMMARIZATION_BUFFER_MAX_SECONDS=15.0
SUMMARIZATION_MODEL=gpt-4o-mini

# Inactivity Monitor
SCOOBY_INACTIVITY_POLL_SECONDS=10
SCOOBY_NO_PARTICIPANTS_GRACE_SECONDS=120
SCOOBY_NO_TRANSCRIPTS_GRACE_SECONDS=300

# Redis
REDIS_URL=redis://localhost:6379/0
SCREENSHARE_BUFFER_SIZE=100
SCREENSHARE_TTL_SECONDS=3600

# S3
SCREENSHARE_S3_BUCKET=scooby-s3-screen-capture
SCREENSHARE_S3_PREFIX=screenshares/
```

---

## Development Workflow

### 1. **Setup**

```bash
# Clone repository
cd /Users/sahanags/Desktop/Pulse\ Core/scooby

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### 2. **Run Development Server**

```bash
# With auto-reload
python -m uvicorn app.main:app --reload

# Or production mode
python -m app.main
```

Server runs on `http://localhost:8000`

### 3. **Testing Bot**

```bash
# Add bot to meeting
curl -X POST http://localhost:8000/add_scooby \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://meet.google.com/abc-defg-hij",
    "isTranscript": false,
    "x_org_name": "test_org",
    "saveTranscript": true
  }'
```

### 4. **Monitoring**

- **Logs:** Check console output for real-time events
- **Files:** Monitor `app/transcripts/` and `app/summaries/`
- **WebSocket:** Connect to `ws://localhost:8000/ws` for status updates

### 5. **Debugging**

**Common Issues:**

1. **Bot not joining:**
   - Check `RECALL_API_KEY`
   - Verify webhook URL is publicly accessible (use ngrok for local dev)
   - Check meeting URL format

2. **No transcripts:**
   - Verify `saveTranscript: true` in request
   - Check webhook endpoint is receiving events
   - Ensure `transcripts_enabled` is set

3. **Summarization failing:**
   - Check `OPENAI_API_KEY`
   - Verify buffer is flushing (check logs)
   - Review LangChain chain execution

4. **Screenshares not saving:**
   - Check AWS credentials
   - Verify S3 bucket exists
   - Check Redis connection
   - Ensure Supabase table exists

### 6. **Key Code Locations**

**To modify buffering logic:**
- `app/service/transcript_buffer.py`
- `app/core/config.py` (buffer settings)

**To modify summarization:**
- `app/service/summarization_service.py`
- `_get_system_prompt()` method

**To modify webhook handling:**
- `app/api/recall.py`
- `recall_webhook()` and `recall_bot_status_webhook()` functions

**To modify storage:**
- `app/service/summary_storage.py`
- `app/service/screenshare_s3.py`

---

## Additional Notes

### Single-Tenant Architecture
- Only one bot can be active at a time
- Attempting to add a second bot returns error
- Global state is cleared when bot leaves/is removed

### Webhook URLs
- Must be publicly accessible
- Use ngrok for local development:
  ```bash
  ngrok http 8000
  # Update webhook URLs in recall_bot.py
  ```

### Error Handling
- All webhook handlers return `{"status": "ok"}` to prevent retries
- Errors are logged but don't crash the server
- Fallback summaries are created if LLM fails

### Performance Considerations
- Buffer size affects memory usage
- Screenshare FPS downsampling reduces storage costs
- Perceptual hashing prevents duplicate frames
- Redis TTL prevents unbounded memory growth

### Future Enhancements
- Multi-tenant support (multiple concurrent bots)
- Real-time summary streaming via WebSocket
- Custom wake word detection
- Advanced analytics dashboard
- Integration with more meeting platforms

---

## Summary

**Scooby Server** is a sophisticated meeting bot that:
1. Joins meetings via Recall.ai
2. Captures transcripts and screenshares in real-time
3. Buffers transcripts intelligently (7 items / 15 seconds)
4. Extracts events and generates summaries using LangChain + OpenAI
5. Searches knowledge bases (Pinecone/Neo4j) for context
6. Stores artifacts in multiple systems (files, S3, Supabase, Redis)
7. Auto-removes on inactivity
8. Uploads transcripts to external API after meeting

The architecture is modular, with clear separation between API, core utilities, and services. The system is designed for reliability with comprehensive error handling and automatic cleanup.
