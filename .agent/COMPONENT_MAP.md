# Scooby Server - Component Interaction Map

## 🎯 System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SCOOBY MEETING BOT SYSTEM                        │
│                                                                           │
│  Purpose: AI-powered meeting assistant with real-time transcription,     │
│           intelligent summarization, and screenshare capture             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Component Hierarchy

```
┌─────────────────────────────────────────────────────────────────┐
│                        ENTRY POINT                               │
│                         app/main.py                              │
│                                                                   │
│  • FastAPI application                                           │
│  • CORS middleware                                               │
│  • Static file serving                                           │
│  • Router registration                                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            │                               │
            ▼                               ▼
┌─────────────────────┐         ┌─────────────────────┐
│   PUBLIC ROUTER     │         │   RECALL ROUTER     │
│   (public.py)       │         │   (recall.py)       │
│                     │         │                     │
│ • GET /             │         │ • WS /ws            │
│ • POST /add_scooby  │         │ • WS /api/ws/...    │
└─────────────────────┘         │ • POST /webhook/... │
                                └──────────┬──────────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    │                      │                      │
                    ▼                      ▼                      ▼
        ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
        │  CORE SERVICES  │   │  AI SERVICES    │   │ STORAGE SERVICES│
        │                 │   │                 │   │                 │
        │ • RecallBot     │   │ • Summarization │   │ • SummaryStorage│
        │ • Participants  │   │ • Buffer        │   │ • Screenshare   │
        │ • Utils         │   │ • Ingestion     │   │ • Vector/Graph  │
        └─────────────────┘   └─────────────────┘   └─────────────────┘
```

---

## 🔄 Request Flow Diagrams

### 1. Bot Creation Flow

```
User Request
    │
    │ POST /add_scooby
    │ {
    │   "meeting_url": "...",
    │   "x_org_name": "...",
    │   "saveTranscript": true
    │ }
    │
    ▼
┌─────────────────────────────────────┐
│  public.py: add_scooby_bot()        │
│  • Validate request                 │
│  • Extract parameters               │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  recall.py: add_bot()               │
│  • Check if bot already exists      │
│  • Initialize global state          │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  RecallBot.add_bots()               │
│  • POST to Recall.ai API            │
│  • Configure webhooks/websockets    │
│  • Set recording options            │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Initialize Components              │
│  • transcript_buffer                │
│  • summary_storage                  │
│  • inactivity_monitor               │
│  • participants_manager             │
└───────────────┬─────────────────────┘
                │
                ▼
┌─────────────────────────────────────┐
│  Return bot_id to user              │
│  Bot joins meeting automatically    │
└─────────────────────────────────────┘
```

### 2. Transcription Processing Flow

```
Recall.ai Webhook
    │
    │ POST /api/webhook/recall
    │ event: "transcript.data"
    │
    ▼
┌─────────────────────────────────────────────┐
│  recall_webhook()                           │
│  • Extract speaker, text, timestamps        │
│  • Check for duplicates                     │
└───────────────┬─────────────────────────────┘
                │
                ├─────────────────────┐
                │                     │
                ▼                     ▼
┌─────────────────────────┐  ┌──────────────────────┐
│  Save to Files          │  │  Add to Buffer       │
│  • summary_storage      │  │  • transcript_buffer │
│  • transcript_writer    │  │  • Check flush       │
└─────────────────────────┘  └──────┬───────────────┘
                                     │
                                     │ should_flush()?
                                     │ (7 items OR 15s)
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │  _process_buffer_and_summarize │
                    │  • Flush buffer                │
                    │  • Get current summary         │
                    └────────┬───────────────────────┘
                             │
                             ▼
                    ┌────────────────────────────────┐
                    │  SummarizationService          │
                    │  • Build LangChain chain       │
                    │  • Extract events              │
                    │  • Search knowledge base       │
                    │  • Generate summary            │
                    │  • Generate suggestion         │
                    └────────┬───────────────────────┘
                             │
                             ▼
                    ┌────────────────────────────────┐
                    │  Save Results                  │
                    │  • Append events to timeline   │
                    │  • Replace global summary      │
                    │  • Log suggestion              │
                    └────────────────────────────────┘
```

### 3. Screenshare Processing Flow

```
Recall.ai WebSocket
    │
    │ WS /api/ws/recall-realtime
    │ event: "video_separate_png.data"
    │
    ▼
┌─────────────────────────────────────────────┐
│  recall_realtime_websocket()                │
│  • Check type == "screenshare"              │
│  • Verify participant is screensharing      │
└───────────────┬─────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────┐
│  FPS Downsampling                           │
│  • Check last frame timestamp               │
│  • Skip if < 2 seconds since last frame     │
└───────────────┬─────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────┐
│  Perceptual Hash Deduplication              │
│  • Decode base64 image                      │
│  • Calculate perceptual hash                │
│  • Check if hash exists                     │
│  • Skip if duplicate                        │
└───────────────┬─────────────────────────────┘
                │
                ├─────────────────────┐
                │                     │
                ▼                     ▼
┌─────────────────────────┐  ┌──────────────────────┐
│  Redis Buffer           │  │  S3 + Supabase       │
│  • screenshare_buffer   │  │  • screenshare_s3    │
│  • push_frame()         │  │  • push_frame()      │
│  • Bounded list         │  │  • Upload to S3      │
│  • TTL: 3600s           │  │  • Save metadata     │
└─────────────────────────┘  └──────────────────────┘
```

### 4. Bot Lifecycle Flow

```
Bot Status Events
    │
    ▼
┌─────────────────────────────────────────────┐
│  recall_bot_status_webhook()                │
│  POST /api/webhook/recall/bot-status        │
└───────────────┬─────────────────────────────┘
                │
                ▼
        ┌───────┴───────┐
        │  Status Type  │
        └───────┬───────┘
                │
    ┌───────────┼───────────┬───────────┐
    │           │           │           │
    ▼           ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
│ joining │ │ in_call │ │  done   │ │  fatal  │
│  _call  │ │         │ │         │ │         │
└────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘
     │           │           │           │
     │           │           │           │
     ▼           ▼           ▼           ▼
  Log only   Log only    Cleanup     Cleanup
                         ┌─────────────────┐
                         │ 1. Flush buffer │
                         │ 2. Process      │
                         │ 3. Ingest       │
                         │ 4. Delete file  │
                         │ 5. Reset state  │
                         │ 6. Stop monitor │
                         └─────────────────┘
```

---

## 🗄️ Data Storage Map

```
┌─────────────────────────────────────────────────────────────────┐
│                      STORAGE LAYER                               │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  LOCAL FILES     │  │  REDIS           │  │  AWS S3          │
│                  │  │                  │  │                  │
│  transcripts/    │  │  screenshare:    │  │  screenshares/   │
│  ├─ Scooby_*.txt │  │  {bot}:{part}    │  │  ├─ {org}/       │
│  └─ {org}_*.txt  │  │                  │  │  │  └─ {bot}/    │
│                  │  │  • Frame buffer  │  │  │     └─ *.png  │
│  summaries/      │  │  • Max 100/part  │  │                  │
│  ├─ *_events.txt │  │  • TTL: 3600s    │  │  • Permanent     │
│  └─ *_summary.txt│  │                  │  │  • Deduplicated  │
└──────────────────┘  └──────────────────┘  └──────────────────┘

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  SUPABASE        │  │  PINECONE        │  │  NEO4J           │
│                  │  │                  │  │                  │
│  screenshare_    │  │  Vector Index    │  │  Knowledge Graph │
│  frames table    │  │                  │  │                  │
│                  │  │  • Embeddings    │  │  • Relationships │
│  • Metadata      │  │  • Semantic      │  │  • Connections   │
│  • Queryable     │  │    search        │  │  • Context       │
│  • Indexed       │  │  • Issues/topics │  │  • History       │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 🧩 Service Dependencies

```
┌─────────────────────────────────────────────────────────────────┐
│                    SERVICE DEPENDENCY GRAPH                      │
└─────────────────────────────────────────────────────────────────┘

recall.py (Main Orchestrator)
    │
    ├─→ RecallBot
    │   └─→ Recall.ai API
    │
    ├─→ ParticipantsManager
    │   └─→ In-memory list
    │
    ├─→ TranscriptBuffer
    │   └─→ In-memory deque
    │
    ├─→ SummarizationService
    │   ├─→ OpenAI API (ChatOpenAI)
    │   ├─→ LangChain (chains, prompts, tools)
    │   ├─→ VectorStore (Pinecone)
    │   ├─→ GraphStore (Neo4j)
    │   └─→ ScreenshareMetadataStore (Supabase)
    │
    ├─→ SummaryStorage
    │   └─→ Local filesystem (aiofiles)
    │
    ├─→ TranscriptWriter
    │   └─→ Local filesystem
    │
    ├─→ TranscriptIngestion
    │   └─→ External API (httpx)
    │
    ├─→ ScreenshareRedisBuffer
    │   └─→ Redis
    │
    ├─→ ScreenshareS3
    │   ├─→ AWS S3 (boto3)
    │   └─→ ScreenshareMetadataStore
    │
    ├─→ InactivityMonitor
    │   ├─→ RecallBot.handle_bot_removal
    │   └─→ ParticipantsManager
    │
    └─→ ConnectionManager
        └─→ WebSocket connections
```

---

## 🎛️ Configuration Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONFIGURATION HIERARCHY                       │
└─────────────────────────────────────────────────────────────────┘

.env file
    │
    ▼
┌─────────────────────────────────────────┐
│  os.getenv() in config.py               │
│  • Load environment variables           │
│  • Apply defaults                       │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  SummarizationConfig (Pydantic)         │
│  • Validate types                       │
│  • Provide defaults                     │
│  • Expose as properties                 │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  get_config() singleton                 │
│  • Returns config instance              │
│  • Used throughout application          │
└───────────────┬─────────────────────────┘
                │
                ▼
        Used by all services
        ┌───────┴───────┐
        │               │
        ▼               ▼
  TranscriptBuffer  SummarizationService
  SummaryStorage    ScreenshareS3
  etc.              etc.
```

---

## 🔐 Authentication & Authorization

```
┌─────────────────────────────────────────────────────────────────┐
│                    API KEY MANAGEMENT                            │
└─────────────────────────────────────────────────────────────────┘

External Service          Environment Variable         Used By
─────────────────────────────────────────────────────────────────
Recall.ai                 RECALL_API_KEY               RecallBot
OpenAI                    OPENAI_API_KEY               SummarizationService
Pinecone                  PINECONE_API_KEY             VectorStore
Neo4j                     NEO4J_USER, NEO4J_PASSWORD   GraphStore
AWS S3                    AWS_ACCESS_KEY_ID,           ScreenshareS3
                          AWS_SECRET_ACCESS_KEY
Supabase                  SUPABASE_SERVICE_ROLE_KEY    ScreenshareMetadataStore
Redis                     REDIS_URL                    ScreenshareRedisBuffer

Note: All keys are loaded from environment variables, never hardcoded
```

---

## 📡 Event System

```
┌─────────────────────────────────────────────────────────────────┐
│                    EVENT TYPES & HANDLERS                        │
└─────────────────────────────────────────────────────────────────┘

WEBHOOK EVENTS (HTTP POST)
──────────────────────────────────────────────────────────────────
Event Type                Handler                   Action
──────────────────────────────────────────────────────────────────
transcript.data           recall_webhook()          • Add to buffer
                                                    • Save to file
                                                    • Check flush

participant_events.join   recall_webhook()          • Add participant
                                                    • Update list

participant_events.leave  recall_webhook()          • Mark left
                                                    • Update list

bot.joining_call          recall_bot_status_        • Log status
                          webhook()

bot.in_call              recall_bot_status_         • Log status
                          webhook()

bot.call_ended           recall_bot_status_         • Flush buffer
                          webhook()                  • Ingest transcript
                                                    • Cleanup

bot.done                 recall_bot_status_         • Flush buffer
                          webhook()                  • Ingest transcript
                                                    • Cleanup

bot.fatal                recall_bot_status_         • Flush buffer
                          webhook()                  • Ingest transcript
                                                    • Cleanup


WEBSOCKET EVENTS
──────────────────────────────────────────────────────────────────
Event Type                Handler                   Action
──────────────────────────────────────────────────────────────────
participant_events.       recall_realtime_          • Add to active set
screenshare_on            websocket()

participant_events.       recall_realtime_          • Remove from set
screenshare_off           websocket()

video_separate_png.data   recall_realtime_          • Downsample FPS
                          websocket()                • Deduplicate
                                                    • Save to Redis/S3
```

---

## 🧠 AI Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│              LANGCHAIN SUMMARIZATION PIPELINE                    │
└─────────────────────────────────────────────────────────────────┘

Input: List[TranscriptItem]
    │
    ▼
┌─────────────────────────────────────────┐
│  Build Input Text                       │
│  • Format timestamps                    │
│  • Include speaker names                │
│  • Add previous summary (continuity)    │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  LangChain Chain Execution              │
│                                         │
│  System Prompt                          │
│  ├─ Role: Meeting assistant            │
│  ├─ Task: Extract events + summarize   │
│  └─ Output: Structured JSON             │
│                                         │
│  Tools Available                        │
│  ├─ search_meeting_knowledge_base()    │
│  │   ├─ issue-related → Pinecone       │
│  │   ├─ MoM-event → Neo4j              │
│  │   └─ general-event → No search      │
│  └─ get_screenshare_frames_by_time()   │
│      └─ Query Supabase metadata         │
│                                         │
│  Model: GPT-4o-mini                     │
│  Temperature: 0.3                       │
│  Max Tokens: 500                        │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  Parse Output (JSON)                    │
│  {                                      │
│    "events": [...],                     │
│    "summary": "...",                    │
│    "suggestion": "..." (optional)       │
│  }                                      │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│  Save Results                           │
│  • Append events to timeline            │
│  • Replace global summary               │
│  • Log suggestion to console            │
└─────────────────────────────────────────┘
```

---

## 🔄 State Transitions

```
┌─────────────────────────────────────────────────────────────────┐
│                    BOT STATE MACHINE                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────┐
│  IDLE   │  current_bot_id = None
└────┬────┘
     │
     │ POST /add_scooby
     │
     ▼
┌─────────┐
│CREATING │  Calling Recall.ai API
└────┬────┘
     │
     │ Success
     │
     ▼
┌─────────┐
│ ACTIVE  │  current_bot_id = bot_id
│         │  transcript_buffer initialized
│         │  summary_storage initialized
│         │  inactivity_monitor started
└────┬────┘
     │
     │ ┌─────────────────────────────┐
     │ │ While Active:               │
     │ │ • Receive transcripts       │
     │ │ • Buffer & summarize        │
     │ │ • Capture screenshares      │
     │ │ • Track participants        │
     │ │ • Monitor inactivity        │
     │ └─────────────────────────────┘
     │
     │ call_ended / done / fatal
     │ OR inactivity timeout
     │
     ▼
┌─────────┐
│CLEANING │  Flush buffer
│   UP    │  Ingest transcript
│         │  Delete files
│         │  Reset state
└────┬────┘
     │
     │ Cleanup complete
     │
     ▼
┌─────────┐
│  IDLE   │  current_bot_id = None
└─────────┘
```

---

## 🎨 Customization Points

```
┌─────────────────────────────────────────────────────────────────┐
│                    WHERE TO CUSTOMIZE                            │
└─────────────────────────────────────────────────────────────────┘

What to Change              File                    Method/Line
─────────────────────────────────────────────────────────────────
Buffer size/time            config.py               buffer_max_items
                            .env                    SUMMARIZATION_*

LLM model                   .env                    SUMMARIZATION_MODEL

Summarization prompt        summarization_          _get_system_prompt()
                            service.py

Event categories            summarization_          EventExtraction class
                            service.py

Knowledge base search       summarization_          search_meeting_
                            service.py              knowledge_base()

File output format          summary_storage.py      save_transcript_line()
                                                    append_events()
                                                    replace_summary()

Screenshare FPS             recall.py               Line ~259
                                                    (ts_relative check)

Inactivity thresholds       .env                    SCOOBY_NO_*_SECONDS

Webhook URLs                recall_bot.py           add_bots() payload

Deduplication logic         recall.py               _is_duplicate_audio_
                                                    segment()
                                                    (perceptual hash)

Bot configuration           recall_bot.py           add_bots() payload
```

---

## 📈 Performance Considerations

```
┌─────────────────────────────────────────────────────────────────┐
│                    PERFORMANCE FACTORS                           │
└─────────────────────────────────────────────────────────────────┘

Component                   Impact              Tuning Options
─────────────────────────────────────────────────────────────────
Transcript Buffer           Memory usage        • buffer_max_items
                            API call frequency  • buffer_max_seconds

Screenshare FPS             Storage costs       • FPS threshold (2.0s)
                            Network bandwidth   • SCREENSHARE_BUFFER_SIZE

Perceptual Hashing          CPU usage           • Hash algorithm
                            Dedup accuracy      • Threshold

Redis Buffer                Memory usage        • SCREENSHARE_BUFFER_SIZE
                            TTL management      • SCREENSHARE_TTL_SECONDS

S3 Uploads                  Network bandwidth   • Frame quality
                            Storage costs       • Deduplication

LLM Calls                   API costs           • Model choice
                            Latency             • Max tokens
                                                • Temperature

Knowledge Base Search       Latency             • Index optimization
                            API costs           • Query filtering
```

---

**Last Updated:** 2025-12-08
**Version:** 2.0.0
