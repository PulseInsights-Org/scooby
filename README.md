# Scooby Server

Scooby Server handles Meeting Bot QA and its related features.
It is a FastAPI server that manages a single tenant – single meeting bot.

---

## Quick Start

1. Add the following values into your `.env` file:

```
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_ANON_KEY=
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the FastAPI server:

* Run directly:

```bash
python -m app.main
```

* Or start development mode with auto-reload:

```bash
python -m uvicorn app.main:app --reload
```

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
  "x_org_id": "string",
  "tenant_id": "string",
  "saveTranscript": true
}
```

**Response:**

* If a bot is successfully added:

```json
{
  "bot_id": "string"
}
```

* If a bot already exists:

```json
{
  "message": "Scooby Bot already exists, Please remove and try again"
}
```

**Notes:**

* Returns the bot ID.
* If already present, a new bot cannot be added.
* Internally handles bot leave or kick-outs.
* Once the call is done or the bot leaves, the transcript is generated and saved in Supabase.

**Example cURL:**

```bash
curl -X POST http://localhost:8000/add_scooby \
  -H "Content-Type: application/json" \
  -d '{
        "meeting_url": "https://example.com/meeting",
        "isTranscript": false,
        "x_org_id": "org123",
        "tenant_id": "tenant123",
        "saveTranscript": true
      }'
```
