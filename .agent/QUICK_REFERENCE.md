# Scooby Server - Quick Reference Guide

## 🚀 Quick Start Commands

```bash
# Start development server
python -m uvicorn app.main:app --reload

# Add bot to meeting
curl -X POST http://localhost:8000/add_scooby \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://meet.google.com/abc-defg-hij",
    "x_org_name": "test_org",
    "saveTranscript": true
  }'
```

---

## 📁 Key Files & Their Purpose

| File | Purpose | When to Modify |
|------|---------|----------------|
| `app/main.py` | FastAPI entry point | Add new routers, middleware |
| `app/api/public.py` | Public endpoints | Add new public APIs |
| `app/api/recall.py` | Webhook handlers | Modify webhook logic |
| `app/core/config.py` | Configuration | Add new config options |
| `app/core/utils.py` | Utilities | Add helper functions |
| `app/service/recall_bot.py` | Recall.ai client | Change bot configuration |
| `app/service/transcript_buffer.py` | Buffering logic | Adjust buffer behavior |
| `app/service/summarization_service.py` | AI summarization | Modify prompts, tools |
| `app/service/summary_storage.py` | File I/O | Change file formats |
| `app/service/screenshare_*.py` | Screenshare handling | Modify screenshare pipeline |

---

## 🔄 Data Flow Cheat Sheet

### Transcription Flow
```
Recall.ai webhook → recall_webhook() → transcript_buffer.add() 
→ should_flush()? → _process_buffer_and_summarize() 
→ SummarizationService.process_segment() → Save to files
```

### Screenshare Flow
```
Recall.ai WebSocket → recall_realtime_websocket() 
→ FPS downsampling → Perceptual hash deduplication 
→ Redis buffer + S3 upload + Supabase metadata
```

### Bot Lifecycle
```
add_bot() → joining_call → in_call → in_call_recording 
→ call_ended/done/fatal → Cleanup & ingestion
```

---

## 🎯 Common Tasks

### Change Buffer Settings
**File:** `app/core/config.py` or `.env`
```python
SUMMARIZATION_BUFFER_MAX_ITEMS=7      # Number of items
SUMMARIZATION_BUFFER_MAX_SECONDS=15.0 # Time in seconds
```

### Modify Summarization Prompt
**File:** `app/service/summarization_service.py`
**Method:** `_get_system_prompt()`
```python
def _get_system_prompt(self) -> str:
    return """Your custom prompt here..."""
```

### Change LLM Model
**File:** `.env`
```bash
SUMMARIZATION_MODEL=gpt-4o-mini  # or gpt-4o, gpt-3.5-turbo
```

### Add New Webhook Event
**File:** `app/api/recall.py`
**Function:** `recall_webhook()`
```python
elif event_type == "your_new_event":
    # Handle event
    pass
```

### Modify File Output Format
**File:** `app/service/summary_storage.py`
**Methods:** `save_transcript_line()`, `append_events()`, `replace_summary()`

---

## 🔧 Configuration Quick Reference

### Required Services
- ✅ Recall.ai account + API key
- ✅ OpenAI API key
- ✅ Pinecone account + API key
- ✅ Neo4j database
- ✅ AWS S3 bucket
- ⚠️ Redis (optional, for screenshare buffer)
- ⚠️ Supabase (optional, for metadata)

### Environment Variables Priority
1. **Critical:** `RECALL_API_KEY`, `OPENAI_API_KEY`
2. **Important:** `PINECONE_API_KEY`, `NEO4J_*`, `AWS_*`
3. **Optional:** `SUPABASE_*`, `REDIS_URL`

---

## 🐛 Debugging Guide

### Bot Not Joining Meeting
```bash
# Check logs for:
- "Failed to add Nexus AI bot to meeting"
- Recall.ai API errors

# Verify:
✓ RECALL_API_KEY is set
✓ Meeting URL is valid
✓ Webhook URL is publicly accessible
```

### No Transcripts Appearing
```bash
# Check:
✓ saveTranscript: true in request
✓ transcripts_enabled = True in logs
✓ Webhook receiving transcript.data events

# Debug:
tail -f app/transcripts/*.txt
```

### Summarization Not Working
```bash
# Check logs for:
- "Error processing buffer and summarizing"
- OpenAI API errors

# Verify:
✓ OPENAI_API_KEY is set
✓ Buffer is flushing (check logs)
✓ transcript_buffer is not None
```

### Screenshares Not Saving
```bash
# Check:
✓ AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
✓ S3 bucket exists (SCREENSHARE_S3_BUCKET)
✓ Redis is running (REDIS_URL)
✓ Supabase table exists (screenshare_frames)

# Debug:
redis-cli KEYS "screenshare:*"
```

---

## 📊 State Management

### Global State Variables (app/api/recall.py)
```python
current_bot_id = None              # Active bot ID
current_meeting_url = None         # Meeting URL
transcripts_enabled = False        # Transcription enabled?
current_x_org_name = None          # Organization name
transcript_buffer = None           # TranscriptBuffer instance
summary_storage = None             # SummaryStorage instance
```

### State Lifecycle
```
add_bot() → Initialize state
  ↓
Meeting in progress → State active
  ↓
call_ended/done/fatal → _set_inactive() → Clear state
```

---

## 🔍 Monitoring & Logs

### Important Log Messages
```
✅ "Bot {bot_id} successfully joined the meeting"
✅ "Buffer flush triggered: item count (7 >= 7)"
✅ "Saved {n} events to timeline"
✅ "Updated global summary: {n} chars"

⚠️ "No current bot set; ignoring realtime event"
⚠️ "Duplicate audio segment detected"
⚠️ "Unhandled realtime event: {event_type}"

❌ "Failed to add Nexus AI bot to meeting"
❌ "Error processing buffer and summarizing"
❌ "Bot {bot_id} encountered a fatal error"
```

### File Locations to Monitor
```
app/transcripts/Scooby_{org}_{id}.txt          # Legacy format
app/transcripts/{org}_{meeting_id}_transcript.txt
app/summaries/{org}_{meeting_id}_events.txt
app/summaries/{org}_{meeting_id}_summary.txt
```

---

## 🎨 Customization Points

### 1. Event Categories
**File:** `app/service/summarization_service.py`
**Class:** `EventExtraction`
```python
event_type: Literal["issue-related", "MoM-event", "general-event"]
# Add your own categories
```

### 2. Knowledge Base Search
**File:** `app/service/summarization_service.py`
**Method:** `search_meeting_knowledge_base()`
```python
# Customize search logic for different event types
```

### 3. Inactivity Thresholds
**File:** `.env`
```bash
SCOOBY_NO_PARTICIPANTS_GRACE_SECONDS=120  # 2 minutes
SCOOBY_NO_TRANSCRIPTS_GRACE_SECONDS=300   # 5 minutes
```

### 4. Screenshare FPS
**File:** `app/api/recall.py`
**Line:** ~259
```python
if ts_relative is not None:
    last_ts = participant_last_ts.get(key)
    if last_ts is not None and (ts_relative - last_ts) < 2.0:  # Change 2.0
        continue
```

---

## 🧪 Testing Checklist

### Before Deploying
- [ ] All environment variables set
- [ ] Webhook URLs are publicly accessible
- [ ] S3 bucket exists and is accessible
- [ ] Redis is running (if using screenshare)
- [ ] Supabase table exists (if using screenshare)
- [ ] Pinecone index exists
- [ ] Neo4j database is accessible
- [ ] Test bot can join a meeting
- [ ] Transcripts are being saved
- [ ] Summaries are being generated
- [ ] Screenshares are being captured (if enabled)

### Test Commands
```bash
# Test bot creation
curl -X POST http://localhost:8000/add_scooby -H "Content-Type: application/json" -d '{"meeting_url": "https://meet.google.com/test", "x_org_name": "test", "saveTranscript": true}'

# Check files
ls -la app/transcripts/
ls -la app/summaries/

# Check Redis
redis-cli KEYS "screenshare:*"

# Check logs
tail -f logs/scooby.log  # If logging to file
```

---

## 📚 Key Concepts

### 1. Single-Tenant Architecture
- Only **one bot** can be active at a time
- Attempting to add a second bot returns error
- Global state is shared across all requests

### 2. Dual-Trigger Buffering
- Flushes on **7 items** OR **15 seconds**
- Whichever condition is met first
- Ensures timely processing with enough context

### 3. Summary Continuity
- Each summary includes **previous summary** as context
- Creates coherent, connected narrative
- Enabled via `config.continuity_enabled`

### 4. Event-Driven Architecture
- Webhooks for transcription and participant events
- WebSockets for screenshare frames
- Asynchronous processing throughout

### 5. Deduplication Strategies
- **Audio:** Segment key (`start:end:speaker`)
- **Screenshare:** Perceptual hash (imagehash.phash)
- Prevents duplicate processing

---

## 🚨 Common Pitfalls

### 1. Webhook URL Not Public
**Problem:** Bot joins but no events received
**Solution:** Use ngrok for local dev
```bash
ngrok http 8000
# Update URLs in recall_bot.py
```

### 2. Missing Environment Variables
**Problem:** Service fails silently
**Solution:** Check all required vars are set
```bash
python -c "from app.core.config import get_config; print(get_config())"
```

### 3. Buffer Not Flushing
**Problem:** No summaries generated
**Solution:** Check buffer configuration and logs
```python
# In recall.py, add debug logging:
logger.info(f"Buffer size: {transcript_buffer.size()}")
logger.info(f"Should flush: {transcript_buffer.should_flush()}")
```

### 4. Screenshare Quota Exceeded
**Problem:** Too many frames stored
**Solution:** Adjust FPS downsampling or buffer size
```bash
SCREENSHARE_BUFFER_SIZE=50  # Reduce from 100
# Or increase FPS threshold from 2.0 to 5.0 seconds
```

### 5. Transcript Ingestion Failing
**Problem:** Files not uploaded to external API
**Solution:** Check API endpoint and credentials
```python
# In transcript_ingestion.py, check base_url
base_url = "https://dev.pulse-api.getpulseinsights.ai"
```

---

## 🔗 External Dependencies

### Recall.ai
- **Docs:** https://docs.recall.ai
- **API:** https://us-west-2.recall.ai/api/v1/
- **Webhooks:** https://docs.recall.ai/docs/real-time-webhook-endpoints

### OpenAI
- **Docs:** https://platform.openai.com/docs
- **Models:** gpt-4o-mini, gpt-4o, gpt-3.5-turbo

### LangChain
- **Docs:** https://python.langchain.com
- **Version:** 0.3.0 (LangChain 1.0)

### Pinecone
- **Docs:** https://docs.pinecone.io
- **Dashboard:** https://app.pinecone.io

### Neo4j
- **Docs:** https://neo4j.com/docs
- **Browser:** http://localhost:7474

---

## 💡 Pro Tips

1. **Use ngrok for local development** - Makes webhooks accessible
2. **Monitor buffer size** - Adjust based on meeting pace
3. **Check logs frequently** - Errors are logged but don't crash server
4. **Test with short meetings first** - Easier to debug
5. **Use environment-specific configs** - Different settings for dev/prod
6. **Keep Redis clean** - Set appropriate TTLs
7. **Monitor S3 costs** - Screenshares can add up
8. **Use Supabase dashboard** - Query metadata easily
9. **Test inactivity monitor** - Ensure cleanup works
10. **Version your prompts** - Track changes to summarization

---

## 📞 Support

For issues or questions:
1. Check logs for detailed error messages
2. Review environment configuration
3. Consult Recall.ai documentation
4. Check OpenAI API status
5. Verify all services are running (Redis, Neo4j, etc.)

---

**Last Updated:** 2025-12-08
**Version:** 2.0.0
