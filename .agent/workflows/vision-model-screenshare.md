---
description: Add Vision Model for Screenshare Analysis
---

# Vision Model Integration for Screenshare Analysis

## 🎯 Objective
Integrate a vision model (OpenAI GPT-4 Vision or similar) to analyze screenshare frames and provide intelligent insights about what's being shared during meetings.

---

## 📊 Current State Analysis

### Existing Infrastructure
✅ **Screenshare Capture Pipeline**
- `ScreenshareRedisBuffer`: Stores recent frames in Redis (bounded buffer)
- `ScreenshareS3`: Uploads frames to S3 for persistence
- `ScreenshareMetadataStore`: Stores frame metadata in Supabase
- Deduplication via perceptual hashing (ImageHash)
- FPS downsampling (1 frame per 2 seconds)

✅ **Current Analysis Service**
- `ScreenAnalysisService` (app/service/screen_analysis_service.py)
- Currently returns metadata-only analysis
- Has placeholder for vision model integration (line 142)

✅ **Integration Points**
- Slack endpoint: `POST /analyze-screen` (app/api/public.py)
- LangChain tool: `get_screenshare_frames_by_time` (summarization_service.py)

### Gaps to Fill
❌ No vision model integration
❌ No image analysis logic
❌ No structured output for visual content
❌ No caching for analyzed frames

---

## 🏗️ Architecture Design

### Option 1: OpenAI GPT-4 Vision (Recommended)
**Pros:**
- Already using OpenAI for summarization
- Excellent multimodal understanding
- Simple API integration
- Supports multiple images in one request

**Cons:**
- Higher cost per image
- Rate limits to consider

**Models:**
- `gpt-4o` (best quality, multimodal)
- `gpt-4o-mini` (cost-effective, good quality)

### Option 2: Google Gemini Vision
**Pros:**
- Good quality
- Competitive pricing
- Large context window

**Cons:**
- Additional API dependency

### Option 3: Open Source (LLaVA, CogVLM)
**Pros:**
- No API costs
- Full control

**Cons:**
- Requires GPU infrastructure
- Deployment complexity

**Recommendation: Start with OpenAI GPT-4o-mini for MVP**

---

## 📐 Implementation Plan

### Phase 1: Core Vision Service (2-3 hours)

#### 1.1 Create Vision Analysis Service
**File:** `app/service/vision_analysis_service.py`

**Features:**
- Analyze single frame with GPT-4 Vision
- Analyze multiple frames (batch analysis)
- Structured output parsing
- Error handling and retries
- Cost tracking

**Output Schema:**
```python
class ScreenAnalysisResult(BaseModel):
    frame_count: int
    time_range: str
    content_type: str  # "code", "presentation", "browser", "terminal", "diagram", etc.
    primary_content: str  # Main content description
    text_detected: Optional[str]  # OCR-like text extraction
    key_elements: List[str]  # Bullet points of notable items
    technical_context: Optional[str]  # Code language, tools visible, etc.
    confidence: float  # 0.0 to 1.0
```

#### 1.2 Update Configuration
**File:** `app/core/config.py`

Add:
```python
# Vision analysis settings
vision_enabled: bool = True
vision_model: str = "gpt-4o-mini"
vision_max_tokens: int = 1000
vision_temperature: float = 0.2
vision_detail_level: str = "auto"  # "low", "high", "auto"
vision_max_images_per_request: int = 5
```

#### 1.3 Add Dependencies
**File:** `requirements.txt`

Already have:
- ✅ `openai>=1.0.0`
- ✅ `Pillow`
- ✅ `ImageHash`

May need:
- `pytesseract` (optional, for OCR fallback)

---

### Phase 2: Enhance ScreenAnalysisService (1-2 hours)

#### 2.1 Update `screen_analysis_service.py`

**Current:** Lines 101-144 (metadata-only analysis)

**Changes:**
1. Inject `VisionAnalysisService` dependency
2. Fetch frames from Redis (already done)
3. Select representative frames (e.g., 3-5 frames from window)
4. Download images from S3 if needed
5. Call vision model with frames
6. Format results for Slack

**Key Decision:** Use Redis base64 images vs. S3 URLs
- **Redis:** Faster, already in memory, limited retention
- **S3:** Persistent, requires download, more reliable
- **Recommendation:** Try Redis first, fallback to S3

#### 2.2 Frame Selection Strategy

For a 10-second window with ~5 frames:
- **Option A:** Analyze all frames (expensive)
- **Option B:** Sample evenly (start, middle, end)
- **Option C:** Detect scene changes (hash-based)

**Recommendation:** Start with Option B (3 frames: start, middle, end)

---

### Phase 3: LangChain Tool Integration (1 hour)

#### 3.1 Update `get_screenshare_frames_by_time` Tool

**Current:** Returns frame count and S3 keys

**Enhanced:** Optionally trigger vision analysis

```python
@tool
def get_screenshare_frames_by_time(
    participant_name: str,
    timestamp_range: str,
    analyze_content: bool = True  # NEW
) -> Dict[str, Any]:
    """
    Fetch screenshare frames and optionally analyze content.
    
    Returns:
        - count: number of frames
        - s3_keys: list of S3 keys
        - analysis: vision model analysis (if analyze_content=True)
    """
```

#### 3.2 Update System Prompt

Add guidance for when to use screenshare analysis:
- When discussing code/technical content
- When someone says "as you can see on my screen"
- When debugging visual issues

---

### Phase 4: Caching & Optimization (1-2 hours)

#### 4.1 Analysis Cache
**Problem:** Same frames analyzed multiple times

**Solution:** Cache in Redis
```
Key: screenshare_analysis:{bot_id}:{participant_id}:{hash}
Value: JSON analysis result
TTL: 1 hour
```

#### 4.2 Cost Optimization
- Track API usage per meeting
- Implement rate limiting
- Add configuration for max analyses per meeting
- Use lower detail level for non-critical frames

#### 4.3 Batch Processing
- Combine multiple frames in single API call (GPT-4V supports this)
- Reduces API calls by ~3x

---

### Phase 5: Slack Integration Enhancement (30 min)

#### 5.1 Update `/analyze-screen` Endpoint

**Current:** Returns metadata-only analysis

**Enhanced:** Returns rich vision analysis

**Format:**
```
📊 Screenshare Analysis (Last 10 seconds)

🎯 Content Type: Code Editor (Python)

📝 What's Visible:
- FastAPI application code
- Function definition for webhook handling
- Import statements for asyncio and logging
- Terminal window showing pytest output

💡 Technical Context:
- Language: Python
- Framework: FastAPI
- Activity: Debugging webhook endpoint

🔍 Key Elements:
• Line 45: async def process_webhook()
• Error message visible in terminal
• VS Code editor with dark theme
```

---

### Phase 6: Testing & Validation (1-2 hours)

#### 6.1 Unit Tests
- Test vision service with sample images
- Test frame selection logic
- Test cache hit/miss scenarios

#### 6.2 Integration Tests
- End-to-end test with mock Recall.ai frames
- Test Slack notification formatting
- Test LangChain tool invocation

#### 6.3 Cost Testing
- Analyze cost per frame
- Estimate monthly costs based on usage patterns
- Set up alerts for budget thresholds

---

## 📝 Detailed Implementation Steps

### Step 1: Create Vision Analysis Service

**File:** `app/service/vision_analysis_service.py`

```python
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import base64
import logging

class ScreenContent(BaseModel):
    content_type: str
    primary_content: str
    text_detected: Optional[str] = None
    key_elements: List[str] = Field(default_factory=list)
    technical_context: Optional[str] = None
    confidence: float = 0.0

class VisionAnalysisService:
    def __init__(self):
        config = get_config()
        self.client = AsyncOpenAI(api_key=config.openai_api_key)
        self.model = config.vision_model
        self.max_tokens = config.vision_max_tokens
        
    async def analyze_frames(
        self, 
        frames: List[Dict[str, Any]],
        context: Optional[str] = None
    ) -> ScreenContent:
        """Analyze screenshare frames with vision model"""
        # Implementation details in actual code
```

### Step 2: Update ScreenAnalysisService

**File:** `app/service/screen_analysis_service.py`

**Changes:**
- Line 32-34: Inject VisionAnalysisService
- Line 101-144: Replace metadata-only logic with vision analysis
- Add frame selection logic
- Add S3 download fallback

### Step 3: Update Configuration

**File:** `app/core/config.py`

Add vision-related settings (see Phase 1.2)

### Step 4: Update Environment Variables

**File:** `.env.example`

```bash
# Vision Analysis Settings (Optional)
VISION_ENABLED=true
VISION_MODEL=gpt-4o-mini
VISION_MAX_TOKENS=1000
VISION_DETAIL_LEVEL=auto
VISION_MAX_IMAGES_PER_REQUEST=5
```

### Step 5: Enhance LangChain Tool

**File:** `app/service/summarization_service.py`

Update `get_screenshare_frames_by_time` tool (lines 148-212)

### Step 6: Add Redis Caching

**File:** `app/service/vision_cache.py` (new)

```python
class VisionAnalysisCache:
    def __init__(self):
        self.redis = redis.from_url(os.getenv("REDIS_URL"))
        
    async def get(self, key: str) -> Optional[Dict]:
        """Get cached analysis"""
        
    async def set(self, key: str, value: Dict, ttl: int = 3600):
        """Cache analysis result"""
```

### Step 7: Update Slack Formatting

**File:** `app/api/public.py`

Update `analyze_screen_from_slack` endpoint (lines 148-197)

---

## 🧪 Testing Strategy

### Manual Testing Checklist
- [ ] Join test meeting with screenshare
- [ ] Trigger `/analyze-screen` from Slack
- [ ] Verify vision analysis in response
- [ ] Test with different content types (code, slides, browser)
- [ ] Test with no screenshare active
- [ ] Test with multiple participants sharing

### Automated Tests
```python
# tests/test_vision_analysis.py
async def test_analyze_code_screenshot():
    service = VisionAnalysisService()
    result = await service.analyze_frames([sample_code_frame])
    assert result.content_type == "code"
    assert "python" in result.technical_context.lower()
```

---

## 💰 Cost Estimation

### OpenAI GPT-4o-mini Pricing (as of Dec 2024)
- Input: $0.15 / 1M tokens
- Output: $0.60 / 1M tokens
- Images: ~170 tokens per image (low detail), ~765 tokens (high detail)

### Estimated Costs
**Scenario:** 1-hour meeting, 3 screenshare analysis requests

- Frames per request: 3
- Tokens per image: ~500 (auto detail)
- Total input tokens: 3 requests × 3 frames × 500 = 4,500 tokens
- Output tokens: ~500 per request = 1,500 tokens

**Cost per meeting:** ~$0.001 (negligible)

**Monthly (100 meetings):** ~$0.10

**With GPT-4o (higher quality):**
- ~10x cost = $1.00/month for 100 meetings

---

## 🚀 Rollout Plan

### Phase 1: MVP (Week 1)
- Implement basic vision analysis
- Slack integration only
- Manual trigger via `/analyze-screen`

### Phase 2: LangChain Integration (Week 2)
- Add tool to summarization service
- Auto-trigger on issue-related events
- Cache implementation

### Phase 3: Optimization (Week 3)
- Batch processing
- Smart frame selection
- Cost monitoring dashboard

### Phase 4: Advanced Features (Week 4+)
- OCR for text extraction
- Diagram/flowchart detection
- Code syntax highlighting in analysis
- Multi-language support

---

## 🔧 Configuration Options

### Conservative (Low Cost)
```env
VISION_ENABLED=true
VISION_MODEL=gpt-4o-mini
VISION_DETAIL_LEVEL=low
VISION_MAX_IMAGES_PER_REQUEST=3
```

### Balanced (Recommended)
```env
VISION_ENABLED=true
VISION_MODEL=gpt-4o-mini
VISION_DETAIL_LEVEL=auto
VISION_MAX_IMAGES_PER_REQUEST=5
```

### High Quality (Best Analysis)
```env
VISION_ENABLED=true
VISION_MODEL=gpt-4o
VISION_DETAIL_LEVEL=high
VISION_MAX_IMAGES_PER_REQUEST=5
```

---

## 📊 Success Metrics

### Technical Metrics
- [ ] Vision analysis latency < 3 seconds
- [ ] Cache hit rate > 50%
- [ ] API error rate < 1%
- [ ] Cost per meeting < $0.01

### User Metrics
- [ ] Slack analysis requests > 10/week
- [ ] Positive feedback on analysis quality
- [ ] Reduction in "what was on the screen?" questions

---

## 🎓 Learning Resources

### OpenAI Vision API
- [GPT-4 Vision Guide](https://platform.openai.com/docs/guides/vision)
- [Vision API Reference](https://platform.openai.com/docs/api-reference/chat/create)

### Best Practices
- Use `detail: "auto"` for cost optimization
- Batch images when possible (up to 10 images)
- Resize large images before sending
- Cache results aggressively

---

## 🔒 Security Considerations

### Data Privacy
- Screenshare frames may contain sensitive information
- Ensure S3 bucket has proper access controls
- Consider data retention policies
- Add opt-out mechanism for sensitive meetings

### API Key Management
- Store OpenAI API key in environment variables
- Rotate keys regularly
- Monitor for unusual usage patterns

---

## 📋 Implementation Checklist

### Prerequisites
- [ ] OpenAI API key configured
- [ ] Redis running (for caching)
- [ ] S3 bucket accessible
- [ ] Supabase metadata store working

### Development
- [ ] Create `VisionAnalysisService`
- [ ] Update `ScreenAnalysisService`
- [ ] Add configuration options
- [ ] Implement caching layer
- [ ] Update LangChain tool
- [ ] Enhance Slack formatting

### Testing
- [ ] Unit tests for vision service
- [ ] Integration tests for full pipeline
- [ ] Manual testing with real meetings
- [ ] Cost validation

### Deployment
- [ ] Update environment variables
- [ ] Deploy to staging
- [ ] Monitor costs and performance
- [ ] Deploy to production
- [ ] Document for users

---

## 🎯 Next Steps

1. **Review this plan** with the team
2. **Estimate effort** (total: ~8-12 hours)
3. **Prioritize phases** (can ship Phase 1 independently)
4. **Set up monitoring** (costs, latency, errors)
5. **Start implementation** with Phase 1

---

## 📞 Support & Questions

If you encounter issues during implementation:
1. Check OpenAI API status
2. Verify Redis connectivity
3. Review S3 permissions
4. Check logs for detailed errors

**Ready to start implementation?** Let me know which phase you'd like to begin with!
