# Google Gemini Vision Integration - Setup Guide

## ✅ Implementation Complete!

The Google Gemini Vision model has been successfully integrated for screenshare analysis.

---

## 🚀 Quick Setup

### 1. Install Dependencies

```bash
# Activate your virtual environment
source .venv/bin/activate

# Install the Gemini SDK
pip install google-generativeai
```

### 2. Get Gemini API Key

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Create a new API key
3. Copy the key

### 3. Configure Environment Variables

Add to your `.env` file:

```bash
# Google Gemini Configuration (Required for vision analysis)
GEMINI_API_KEY=your_actual_gemini_api_key_here
VISION_ENABLED=true
VISION_MODEL=gemini-1.5-flash
VISION_MAX_TOKENS=2000
VISION_MAX_IMAGES_PER_REQUEST=10
```

### 4. Restart the Server

```bash
python -m uvicorn app.main:app --reload
```

---

## 🎯 How It Works

### Architecture

```
Slack /capture command
    ↓
POST /analyze-screen (returns immediately)
    ↓
Background Task Started
    ↓
1. Send "Analyzing..." message to Slack
    ↓
2. Load frames from Redis (last 10 seconds)
    ↓
3. Select 10 representative frames
    ↓
4. Build rich context (meeting, participant, timeline)
    ↓
5. Call Gemini Vision API
    ↓
6. Parse structured response
    ↓
7. Format for Slack
    ↓
8. Send analysis result to Slack
```

### Key Features

✅ **No Timeout Issues**: Returns immediately to Slack, processes in background
✅ **Rich Context**: Includes meeting ID, participant name, org, timeline
✅ **10 Frames Analyzed**: Comprehensive coverage of the screenshare window
✅ **Structured Output**: Content type, primary content, text detection, key elements, technical context
✅ **Error Handling**: Graceful fallbacks and user-friendly error messages

---

## 📊 Configuration Options

### Models Available

- **`gemini-1.5-flash`** (Recommended): Fast, cost-effective, good quality
- **`gemini-1.5-pro`**: Higher quality, slower, more expensive
- **`gemini-pro-vision`**: Legacy model

### Performance Tuning

**Fast & Cheap** (Current Default):
```env
VISION_MODEL=gemini-1.5-flash
VISION_MAX_TOKENS=2000
VISION_MAX_IMAGES_PER_REQUEST=10
```

**High Quality**:
```env
VISION_MODEL=gemini-1.5-pro
VISION_MAX_TOKENS=4000
VISION_MAX_IMAGES_PER_REQUEST=10
```

**Budget Mode**:
```env
VISION_MODEL=gemini-1.5-flash
VISION_MAX_TOKENS=1000
VISION_MAX_IMAGES_PER_REQUEST=5
```

---

## 🧪 Testing

### 1. Start a Meeting with Screenshare

```bash
# Join a test meeting
curl -X POST http://localhost:8000/add_scooby \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://meet.google.com/your-meeting",
    "x_org_name": "test_org",
    "saveTranscript": true
  }'
```

### 2. Trigger Analysis from Slack

Use your Slack slash command (e.g., `/capture`) which should be mapped to:
```
POST https://your-server.com/analyze-screen
```

### 3. Expected Response

**Immediate Response** (within 1 second):
```
🔍 Analyzing screenshare frames... This may take a few seconds.
```

**Analysis Result** (after 3-10 seconds):
```
📊 Screenshare Analysis (10 frames analyzed)

🎯 Content Type: Code Editor

📝 What's Visible:
Python code in VS Code showing FastAPI application with webhook handlers...

💬 Text Detected:
```python
async def analyze_screen_from_slack(request: Request):
    ...
```

💡 Technical Context:
Language: Python, Framework: FastAPI, Editor: VS Code

🔍 Key Elements:
• Line 148: async function definition
• Import statements for FastAPI
• Dark theme editor
• Terminal window visible

⏱️ Time Range: 0:05 - 0:15
✅ Confidence: 85%
```

---

## 🐛 Troubleshooting

### Issue: "Vision analysis is not enabled or configured"

**Solution**: Check that `GEMINI_API_KEY` is set in `.env`

```bash
# Verify environment variable
echo $GEMINI_API_KEY

# Or check in Python
python -c "from app.core.config import get_config; print(get_config().gemini_api_key)"
```

### Issue: "No recent screenshare frames available"

**Possible Causes**:
1. No one is sharing screen in the meeting
2. Redis buffer is empty (frames expired)
3. Screenshare capture is not working

**Solution**: 
- Verify someone is actively sharing screen
- Check Redis: `redis-cli KEYS "screenshare:*"`
- Check logs for screenshare capture errors

### Issue: API Rate Limits

**Solution**: Reduce frequency or number of images

```env
VISION_MAX_IMAGES_PER_REQUEST=5  # Reduce from 10
```

### Issue: Analysis Taking Too Long

**Solution**: Use faster model or reduce tokens

```env
VISION_MODEL=gemini-1.5-flash  # Fastest
VISION_MAX_TOKENS=1000  # Reduce from 2000
```

---

## 💰 Cost Estimation

### Gemini 1.5 Flash Pricing (as of Dec 2024)

- **Input**: $0.075 per 1M tokens
- **Output**: $0.30 per 1M tokens
- **Images**: ~258 tokens per image

### Example Calculation

**Per Analysis Request**:
- 10 images × 258 tokens = 2,580 input tokens
- Context + prompt ≈ 500 tokens
- Output ≈ 500 tokens
- **Total**: ~3,580 tokens

**Cost**: ~$0.0003 per analysis (negligible)

**Monthly** (100 analyses): ~$0.03

**Very affordable!** 🎉

---

## 📝 Files Modified

1. ✅ `requirements.txt` - Added `google-generativeai`
2. ✅ `app/core/config.py` - Added Gemini vision settings
3. ✅ `app/service/gemini_vision_service.py` - **NEW** Vision service
4. ✅ `app/service/screen_analysis_service.py` - Integrated vision analysis
5. ✅ `app/api/public.py` - Fixed timeout with background tasks
6. ✅ `.env.example` - Added Gemini configuration

---

## 🎓 Next Steps

### Optional Enhancements

1. **Add Caching**: Cache analysis results in Redis to avoid re-analyzing same frames
2. **Add to LangChain Tool**: Integrate with `get_screenshare_frames_by_time` tool
3. **Auto-trigger**: Automatically analyze when issue-related events are detected
4. **OCR Enhancement**: Add dedicated OCR for better text extraction
5. **Diagram Detection**: Special handling for flowcharts, architecture diagrams
6. **Multi-language**: Support for non-English text detection

### Monitoring

Add logging to track:
- API call latency
- Token usage
- Error rates
- Cost per meeting

---

## ✨ Summary

You now have a fully functional Google Gemini Vision integration that:

- ✅ Analyzes screenshare frames in real-time
- ✅ Provides detailed, structured analysis
- ✅ Handles Slack timeouts gracefully
- ✅ Includes rich context for better results
- ✅ Analyzes 10 frames for comprehensive coverage
- ✅ Costs ~$0.0003 per analysis

**Ready to use!** Just add your `GEMINI_API_KEY` and restart the server. 🚀
