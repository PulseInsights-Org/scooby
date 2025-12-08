# Scooby Server - Development Guide

## 🎯 Common Development Workflows

This guide covers the most common tasks you'll perform when working on Scooby.

---

## 1️⃣ Setting Up Your Development Environment

### Initial Setup

```bash
# Navigate to project
cd /Users/sahanags/Desktop/Pulse\ Core/scooby

# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate  # Mac/Linux
# OR
.venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env  # or use your preferred editor
```

### Required Services Setup

```bash
# 1. Start Redis (for screenshare buffer)
redis-server

# 2. Start Neo4j (for knowledge graph)
# Download from https://neo4j.com/download/
# Or use Docker:
docker run -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:latest

# 3. Setup ngrok (for local webhook testing)
ngrok http 8000
# Copy the HTTPS URL and update webhook URLs in recall_bot.py
```

### Environment Variables Checklist

```bash
# Required
✓ RECALL_API_KEY
✓ OPENAI_API_KEY
✓ PINECONE_API_KEY
✓ NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
✓ AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION

# Optional but recommended
○ SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
○ REDIS_URL
○ SCREENSHARE_S3_BUCKET
```

---

## 2️⃣ Running the Application

### Development Mode (with auto-reload)

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Production Mode

```bash
python -m app.main
```

### With Custom Port

```bash
python -m uvicorn app.main:app --reload --port 8080
```

### With Logging

```bash
python -m uvicorn app.main:app --reload --log-level debug
```

---

## 3️⃣ Testing the Bot

### Test Bot Creation

```bash
# Using curl
curl -X POST http://localhost:8000/add_scooby \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://meet.google.com/abc-defg-hij",
    "x_org_name": "test_org",
    "saveTranscript": true
  }'

# Expected response:
# {"bot_id": "abc123xyz"}
```

### Test WebSocket Connection

```python
# test_websocket.py
import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://localhost:8000/ws"
    async with websockets.connect(uri) as websocket:
        message = await websocket.recv()
        print(f"Received: {json.loads(message)}")

asyncio.run(test_ws())
```

### Monitor Logs

```bash
# Watch transcripts being created
watch -n 1 'ls -lh app/transcripts/'

# Watch summaries being created
watch -n 1 'ls -lh app/summaries/'

# Tail transcript file
tail -f app/transcripts/Scooby_test_org_*.txt

# Tail summary file
tail -f app/summaries/test_org_*_summary.txt
```

---

## 4️⃣ Modifying the Summarization Logic

### Change the System Prompt

**File:** `app/service/summarization_service.py`

```python
def _get_system_prompt(self) -> str:
    return """
    You are an AI meeting assistant. Your task is to:
    
    1. Extract key events from meeting transcripts
    2. Categorize each event as:
       - issue-related: Technical problems, blockers
       - MoM-event: References to previous meetings
       - general-event: Everything else
    3. Generate a comprehensive meeting summary
    
    # YOUR CUSTOM INSTRUCTIONS HERE
    
    Be concise but thorough. Focus on actionable items.
    """
```

### Add a New Event Category

**File:** `app/service/summarization_service.py`

```python
# 1. Update EventExtraction model
class EventExtraction(BaseModel):
    timestamp: str = Field(description="Time range in format '00:15-00:18'")
    event: str = Field(description="Detailed description")
    person: str = Field(description="Person involved")
    event_type: Literal[
        "issue-related",
        "MoM-event",
        "general-event",
        "action-item",  # NEW CATEGORY
    ] = Field(description="Type of event")

# 2. Update search logic
def search_meeting_knowledge_base(
    query: str,
    event_type: Literal["issue-related", "MoM-event", "general-event", "action-item"]
):
    if event_type == "action-item":
        # Custom search logic for action items
        return "Search action items database..."
    # ... rest of logic
```

### Change the LLM Model

**Option 1: Environment Variable**
```bash
# In .env
SUMMARIZATION_MODEL=gpt-4o  # More capable, higher cost
# OR
SUMMARIZATION_MODEL=gpt-3.5-turbo  # Faster, lower cost
```

**Option 2: Code**
```python
# In app/core/config.py
model_name: str = os.getenv("SUMMARIZATION_MODEL", "gpt-4o")
```

### Adjust Temperature and Max Tokens

**File:** `app/core/config.py`

```python
class SummarizationConfig(BaseModel):
    temperature: float = 0.3  # Lower = more deterministic
    max_tokens: int = 500     # Increase for longer summaries
```

---

## 5️⃣ Modifying the Buffer Logic

### Change Buffer Thresholds

**Option 1: Environment Variables**
```bash
# In .env
SUMMARIZATION_BUFFER_MAX_ITEMS=10    # Increase from 7
SUMMARIZATION_BUFFER_MAX_SECONDS=20.0  # Increase from 15
```

**Option 2: Code**
```python
# In app/core/config.py
buffer_max_items: int = int(os.getenv("SUMMARIZATION_BUFFER_MAX_ITEMS", "10"))
buffer_max_seconds: float = float(os.getenv("SUMMARIZATION_BUFFER_MAX_SECONDS", "20.0"))
```

### Add Custom Flush Logic

**File:** `app/service/transcript_buffer.py`

```python
def should_flush(self) -> bool:
    if len(self._buffer) == 0:
        return False

    # Existing logic
    if len(self._buffer) >= self.max_items:
        return True
    
    if self._first_item_time:
        elapsed = (datetime.now(timezone.utc) - self._first_item_time).total_seconds()
        if elapsed >= self.max_seconds:
            return True
    
    # NEW: Flush if specific keywords detected
    for item in self._buffer:
        if any(keyword in item.text.lower() for keyword in ["urgent", "critical", "asap"]):
            logger.info("Flush triggered by urgent keyword")
            return True
    
    return False
```

---

## 6️⃣ Adding a New Webhook Event

### Step 1: Update Recall Bot Configuration

**File:** `app/service/recall_bot.py`

```python
"realtime_endpoints": [
    {
        "type": "webhook",
        "url": "https://your-domain/api/webhook/recall",
        "events": [
            "transcript.data",
            "participant_events.join",
            "participant_events.leave",
            "your_new_event",  # ADD HERE
        ]
    }
]
```

### Step 2: Add Handler

**File:** `app/api/recall.py`

```python
@router.post("/api/webhook/recall")
async def recall_webhook(request: Request):
    payload = await request.json()
    event_type = payload.get("event")
    
    # ... existing handlers ...
    
    elif event_type == "your_new_event":
        # Extract data
        data = payload.get("data", {})
        
        # Process event
        logger.info(f"Received new event: {data}")
        
        # Update state if needed
        # Call services if needed
        
    return {"status": "ok"}
```

---

## 7️⃣ Modifying Screenshare Processing

### Change FPS Downsampling

**File:** `app/api/recall.py` (line ~259)

```python
# Current: 1 frame every 2 seconds
if last_ts is not None and (ts_relative - last_ts) < 2.0:
    continue

# Change to 1 frame every 5 seconds
if last_ts is not None and (ts_relative - last_ts) < 5.0:
    continue
```

### Change Deduplication Sensitivity

**File:** `app/api/recall.py`

```python
# Current: Exact hash match
img_hash = str(imagehash.phash(image))
if img_hash in hashes:
    continue

# Change to allow similar frames (Hamming distance)
img_hash = imagehash.phash(image)
for existing_hash in hashes:
    if img_hash - existing_hash < 5:  # Allow 5-bit difference
        logger.info("Similar frame detected (skipped)")
        continue
```

### Add Screenshare Analysis

**File:** `app/api/recall.py`

```python
# After deduplication, before saving
try:
    image = Image.open(io.BytesIO(frame_bytes))
    img_hash = str(imagehash.phash(image))
    
    # NEW: Analyze image content
    # Example: Detect if it's a code editor
    width, height = image.size
    dominant_color = image.resize((1, 1)).getpixel((0, 0))
    
    metadata = {
        "width": width,
        "height": height,
        "dominant_color": dominant_color,
        # Add more analysis as needed
    }
    
    # Save with metadata
    await screenshare_buffer.push_frame(
        # ... existing params ...
        metadata=metadata  # Add this
    )
```

---

## 8️⃣ Customizing File Output

### Change Transcript Format

**File:** `app/service/summary_storage.py`

```python
async def save_transcript_line(
    self,
    speaker: str,
    text: str,
    start_timestamp: Optional[float] = None,
    end_timestamp: Optional[float] = None
) -> None:
    # Current format: [00:15-00:18] Alice: Hello
    
    # NEW: Add date/time
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] [{start_time_str}-{end_time_str}] {speaker}: {text}\n"
    
    # OR: JSON format
    import json
    line = json.dumps({
        "timestamp": now,
        "start": start_time_str,
        "end": end_time_str,
        "speaker": speaker,
        "text": text
    }) + "\n"
    
    async with aiofiles.open(self.transcript_path, 'a', encoding='utf-8') as f:
        await f.write(line)
```

### Change Events Format

**File:** `app/service/summary_storage.py`

```python
async def append_events(self, events: List[Dict[str, Any]]) -> None:
    lines = []
    for event in events:
        # Current format: [00:15-00:18] [Event description] [by Alice]
        
        # NEW: Add event type
        timestamp = event.get('timestamp', 'N/A')
        event_desc = event.get('event', 'N/A')
        person = event.get('person', 'N/A')
        event_type = event.get('event_type', 'general-event')
        
        line = f"[{timestamp}] [{event_type}] {event_desc} (by {person})\n"
        lines.append(line)
    
    async with aiofiles.open(self.events_path, 'a', encoding='utf-8') as f:
        await f.writelines(lines)
```

---

## 9️⃣ Adding Knowledge Base Integration

### Add a New Tool to LangChain

**File:** `app/service/summarization_service.py`

```python
def __init__(self):
    # ... existing code ...
    
    # NEW TOOL
    @tool
    def search_company_wiki(query: str) -> str:
        """Search company wiki for relevant information.
        
        Args:
            query: Search query
            
        Returns:
            Relevant wiki content
        """
        # Implement your search logic
        # Example: Call internal API
        import httpx
        response = httpx.get(
            "https://wiki.company.com/api/search",
            params={"q": query}
        )
        return response.json().get("content", "No results found")
    
    # Add to tools list
    tools = [
        search_meeting_knowledge_base,
        get_screenshare_frames_by_time,
        search_company_wiki,  # NEW
    ]
```

### Integrate with External API

**File:** `app/service/summarization_service.py`

```python
def search_meeting_knowledge_base(query: str, event_type: str):
    if event_type == "issue-related":
        # Existing Pinecone search
        results = self.vector_store.search(query)
        
        # NEW: Also search external issue tracker
        import httpx
        jira_results = httpx.get(
            "https://jira.company.com/api/search",
            params={"jql": f"text ~ '{query}'"},
            headers={"Authorization": f"Bearer {os.getenv('JIRA_API_KEY')}"}
        ).json()
        
        # Combine results
        combined = f"Vector DB: {results}\n\nJira: {jira_results}"
        return combined
```

---

## 🔟 Debugging Common Issues

### Issue: Bot Not Joining Meeting

**Debug Steps:**

```python
# 1. Add debug logging in recall_bot.py
async def add_bots(self, meeting_url: str, bot_name: str = "scooby"):
    logger.info(f"Attempting to add bot to: {meeting_url}")
    logger.debug(f"Payload: {payload}")
    
    response = await client.post(recall_api_url, json=payload, headers=headers)
    logger.info(f"Response status: {response.status_code}")
    logger.debug(f"Response body: {response.text}")

# 2. Check webhook URL
# Ensure ngrok is running and URL is updated
ngrok http 8000
# Update URLs in recall_bot.py lines 31 and 40

# 3. Verify Recall.ai API key
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('RECALL_API_KEY'))"
```

### Issue: No Transcripts Appearing

**Debug Steps:**

```python
# 1. Add logging in recall_webhook()
@router.post("/api/webhook/recall")
async def recall_webhook(request: Request):
    payload = await request.json()
    logger.info(f"Received webhook: {payload}")
    
    if event_type == "transcript.data":
        logger.info(f"Transcript event received")
        logger.debug(f"Speaker: {speaker}, Text: {spoken_text}")

# 2. Check global state
# Add to recall_webhook()
logger.info(f"current_bot_id: {current_bot_id}")
logger.info(f"transcripts_enabled: {transcripts_enabled}")
logger.info(f"transcript_buffer: {transcript_buffer}")

# 3. Verify files are being created
ls -la app/transcripts/
ls -la app/summaries/
```

### Issue: Summarization Failing

**Debug Steps:**

```python
# 1. Add try-except in _process_buffer_and_summarize()
async def _process_buffer_and_summarize():
    try:
        items = transcript_buffer.flush()
        logger.info(f"Processing {len(items)} items")
        
        result = await summarization_service.process_segment(items, current_summary)
        logger.info(f"Summarization result: {result}")
        
    except Exception as e:
        logger.exception(f"Summarization failed: {e}")
        # Print full traceback
        import traceback
        traceback.print_exc()

# 2. Test LangChain chain directly
python -c "
from app.service.summarization_service import SummarizationService
from app.service.transcript_buffer import TranscriptItem
from datetime import datetime, timezone

service = SummarizationService()
items = [
    TranscriptItem('Alice', 'Hello', datetime.now(timezone.utc), 0.0, 1.0),
    TranscriptItem('Bob', 'Hi', datetime.now(timezone.utc), 1.0, 2.0),
]
result = service.process_segment(items)
print(result)
"
```

---

## 1️⃣1️⃣ Performance Optimization

### Reduce API Costs

```python
# 1. Increase buffer size (fewer API calls)
SUMMARIZATION_BUFFER_MAX_ITEMS=15  # Instead of 7

# 2. Use cheaper model
SUMMARIZATION_MODEL=gpt-3.5-turbo  # Instead of gpt-4o-mini

# 3. Reduce max tokens
# In config.py
max_tokens: int = 300  # Instead of 500
```

### Reduce Storage Costs

```python
# 1. Increase screenshare FPS threshold
# In recall.py, change from 2.0 to 5.0 seconds
if (ts_relative - last_ts) < 5.0:
    continue

# 2. Reduce buffer size
SCREENSHARE_BUFFER_SIZE=50  # Instead of 100

# 3. Add TTL to S3 objects
# In screenshare_s3.py
s3_client.put_object(
    # ... existing params ...
    Tagging='expiry=30days'  # Add lifecycle policy
)
```

### Improve Response Time

```python
# 1. Use async operations
# Already implemented throughout

# 2. Reduce polling frequency
SCOOBY_INACTIVITY_POLL_SECONDS=30  # Instead of 10

# 3. Cache knowledge base results
from functools import lru_cache

@lru_cache(maxsize=100)
def search_knowledge_base(query: str):
    # Search logic
    pass
```

---

## 1️⃣2️⃣ Adding Tests

### Unit Test Example

```python
# tests/test_transcript_buffer.py
import pytest
from app.service.transcript_buffer import TranscriptBuffer

def test_buffer_flush_on_item_count():
    buffer = TranscriptBuffer(max_items=3, max_seconds=100)
    
    buffer.add("Alice", "Hello", 0.0, 1.0)
    assert not buffer.should_flush()
    
    buffer.add("Bob", "Hi", 1.0, 2.0)
    assert not buffer.should_flush()
    
    buffer.add("Charlie", "Hey", 2.0, 3.0)
    assert buffer.should_flush()
    
    items = buffer.flush()
    assert len(items) == 3
    assert buffer.is_empty()

def test_buffer_flush_on_time():
    import time
    buffer = TranscriptBuffer(max_items=10, max_seconds=2)
    
    buffer.add("Alice", "Hello", 0.0, 1.0)
    assert not buffer.should_flush()
    
    time.sleep(2.5)
    assert buffer.should_flush()
```

### Integration Test Example

```python
# tests/test_api.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_add_scooby():
    response = client.post("/add_scooby", json={
        "meeting_url": "https://meet.google.com/test",
        "x_org_name": "test_org",
        "saveTranscript": True
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "bot_id" in data or "message" in data
```

### Run Tests

```bash
# Install pytest
pip install pytest pytest-asyncio

# Run all tests
pytest

# Run specific test file
pytest tests/test_transcript_buffer.py

# Run with coverage
pip install pytest-cov
pytest --cov=app tests/
```

---

## 1️⃣3️⃣ Deployment Checklist

### Pre-Deployment

- [ ] All environment variables set in production
- [ ] Webhook URLs point to production domain
- [ ] SSL certificates configured
- [ ] Redis is running and accessible
- [ ] Neo4j is running and accessible
- [ ] S3 bucket exists and has correct permissions
- [ ] Supabase table exists (if using screenshare)
- [ ] Pinecone index exists
- [ ] All API keys are valid
- [ ] Logs are configured (file or service)
- [ ] Error monitoring set up (Sentry, etc.)

### Deployment Commands

```bash
# 1. Pull latest code
git pull origin main

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Install/update dependencies
pip install -r requirements.txt

# 4. Run migrations (if any)
# python migrate.py

# 5. Start application
# Option 1: Direct
python -m app.main

# Option 2: With process manager (recommended)
pip install supervisor
supervisord -c supervisor.conf

# Option 3: With systemd
sudo systemctl start scooby
sudo systemctl enable scooby
```

### Post-Deployment

```bash
# 1. Check application is running
curl http://localhost:8000/

# 2. Test bot creation
curl -X POST http://your-domain/add_scooby \
  -H "Content-Type: application/json" \
  -d '{"meeting_url": "...", "x_org_name": "test", "saveTranscript": true}'

# 3. Monitor logs
tail -f /var/log/scooby/app.log

# 4. Check resource usage
htop
# Look for python processes

# 5. Verify external services
redis-cli ping
# Should return PONG
```

---

## 1️⃣4️⃣ Useful Commands

### Development

```bash
# Format code
pip install black
black app/

# Lint code
pip install flake8
flake8 app/

# Type checking
pip install mypy
mypy app/

# Check dependencies
pip list --outdated

# Update dependencies
pip install --upgrade -r requirements.txt
```

### Debugging

```bash
# Interactive Python shell with app context
python -i -c "from app.main import app; from app.core.config import get_config"

# Check Redis keys
redis-cli KEYS "*"

# Check Redis screenshare buffers
redis-cli KEYS "screenshare:*"

# Get Redis key value
redis-cli GET "screenshare:bot123:participant456"

# Check S3 objects
aws s3 ls s3://scooby-s3-screen-capture/screenshares/ --recursive

# Query Supabase
# Use Supabase dashboard or psql
```

### Monitoring

```bash
# Watch file changes
watch -n 1 'ls -lh app/transcripts/ app/summaries/'

# Monitor network traffic
sudo tcpdump -i any port 8000

# Check open files
lsof -p $(pgrep -f "python.*app.main")

# Monitor CPU/Memory
top -p $(pgrep -f "python.*app.main")
```

---

## 📚 Additional Resources

### Documentation
- **Recall.ai:** https://docs.recall.ai
- **LangChain:** https://python.langchain.com
- **FastAPI:** https://fastapi.tiangolo.com
- **Pinecone:** https://docs.pinecone.io
- **Neo4j:** https://neo4j.com/docs

### Tools
- **ngrok:** https://ngrok.com (for local webhook testing)
- **Postman:** https://www.postman.com (for API testing)
- **Redis Commander:** https://github.com/joeferner/redis-commander (Redis GUI)
- **Neo4j Browser:** http://localhost:7474 (Neo4j GUI)

---

**Happy Coding! 🚀**

**Last Updated:** 2025-12-08
**Version:** 2.0.0
