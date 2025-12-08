# Scooby Server - Changelog

## [2.0.1] - 2025-12-08

### Added
- **Frontend Configuration API**: New `/api/config` endpoint to serve configuration to frontend
  - Returns WebSocket URL and public base URL
  - Automatically converts `https://` to `wss://` for WebSocket connections
  - Provides fallback to localhost for development

### Changed
- **Centralized Configuration Management**: Refactored `RecallBot` class to use centralized configuration pattern
  - Moved `PUBLIC_BASE_URL` and `RECALL_API_KEY` to `SummarizationConfig` in `config.py`
  - Updated `RecallBot` to use `self.config` instead of direct `os.getenv()` calls
  - Follows established pattern used throughout the codebase
  - Improves maintainability and consistency

- **Dynamic URL Configuration**: Updated `RecallBot` class to use `PUBLIC_BASE_URL` environment variable instead of hardcoded ngrok URLs
  - Webhook URL now dynamically constructed from `PUBLIC_BASE_URL`
  - WebSocket URL automatically converted from `https://` to `wss://`
  - Camera webpage URL uses `PUBLIC_BASE_URL`
  - Makes deployment more flexible and environment-agnostic

- **Frontend Dynamic Configuration**: Updated frontend JavaScript to load configuration from backend
  - Removed hardcoded WebSocket URL from `bot.js`
  - Added `loadConfig()` function to fetch configuration from `/api/config`
  - WebSocket URL now dynamically loaded on page load
  - Provides fallback configuration for development

### Files Modified
- `app/core/config.py`
  - Added `public_base_url` field to `SummarizationConfig`
  - Added `recall_api_key` field to `SummarizationConfig`
  
- `app/api/public.py`
  - Added `from app.core.config import get_config`
  - Added new `/api/config` endpoint to serve frontend configuration
  - Returns `wsUrl` and `publicBaseUrl` for frontend use
  
- `app/service/recall_bot.py`
  - Removed `import os` 
  - Added `from app.core.config import get_config`
  - Updated `__init__()` to initialize `self.config = get_config()`
  - Updated `add_bots()` to use `self.config.recall_api_key` and `self.config.public_base_url`
  - Updated `handle_bot_removal()` to use `self.config.recall_api_key`
  - Updated `send_chat_message()` to use `self.config.recall_api_key`

- `app/static/js/bot.js`
  - Added `config` object to store configuration from backend
  - Added `loadConfig()` function to fetch configuration from `/api/config`
  - Updated `connectWebSocket()` to use `config.wsUrl` instead of hardcoded URL
  - Updated `DOMContentLoaded` to load config before initializing WebSocket
  - Added fallback configuration for development

### Migration Guide
To use the new configuration:

1. **Update your `.env` file:**
   ```bash
   # Add this line with your public URL (ngrok, production domain, etc.)
   PUBLIC_BASE_URL=https://your-domain-here.ngrok-free.dev
   ```

2. **No code changes needed** - The application will automatically use the URL from `.env`

3. **When switching environments:**
   - Development: `PUBLIC_BASE_URL=https://your-ngrok-url.ngrok-free.dev`
   - Staging: `PUBLIC_BASE_URL=https://staging.yourdomain.com`
   - Production: `PUBLIC_BASE_URL=https://api.yourdomain.com`

### Benefits
- ✅ No more hardcoded URLs in code
- ✅ Easy environment switching (dev/staging/prod)
- ✅ Single source of truth for public URL
- ✅ Automatic WebSocket protocol conversion
- ✅ Better security (URLs not committed to git)

---

## [2.0.0] - 2025-12-02

### Added
- LangChain 1.0 integration
- OpenAI GPT-4o-mini for summarization
- Intelligent transcript buffering (7 items / 15 seconds)
- Dual file storage system (transcripts + summaries)
- Summary continuity across chunks
- Configurable buffer and timing
- Event extraction with categorization
- Knowledge base integration (Pinecone + Neo4j)
- Screenshare capture and storage
- Inactivity monitoring and auto-removal

### Removed
- Google Gemini Live API integration
- Real-time audio streaming via WebSocket
- "Scooby" wake word detection

### Changed
- Switched from Gemini to OpenAI for cost-effectiveness
- Improved record-keeping with dual file system
- Simplified configuration with environment variables
- Automatic processing (no wake word needed)

---

## [1.0.0] - Initial Release

### Added
- Initial release with Gemini Live integration
- Real-time audio responses
- Basic transcription storage
- Recall.ai meeting bot integration
- WebSocket communication
- Participant tracking

---

**Last Updated:** 2025-12-08
