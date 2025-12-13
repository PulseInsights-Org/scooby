# Endpoint README

## Overview
Scooby exposes a FastAPI surface that lets web dashboards, Slack slash commands, or other clients spin up Recall bots and consume analytics context (customer summary + recent interactions).

## HTTP Endpoints

### Add Scooby Bot
- **Method**: POST
- **Path**: `/add_scooby`
- **Sample JSON Payload**:
```json
{
  "meeting_url": "https://zoom.us/j/123",
  "isTranscript": false,
  "tenant_id": "tenant_001",
  "saveTranscript": true,
  "customer_id": "cust_001",
  "privacy_mode": "public"
}
```

### Remove Scooby Bot
- **Method**: POST
- **Path**: `/remove_scooby`
- **Sample JSON Payload**:
```json
{
  "bot_id": "your-bot-id"
}
```

### Send Summary to Slack
- **Method**: POST
- **Path**: `/summary`
- **Sample Form Payload** (URL-encoded):
```text
channel_id=your-slack-channel-id
```

### Send Suggestion to Slack
- **Method**: POST
- **Path**: `/suggest`
- **Sample Form Payload** (URL-encoded):
```text
channel_id=your-slack-channel-id
```

### Analyze Screen and Send to Slack
- **Method**: POST
- **Path**: `/analyze-screen`
- **Sample Form Payload** (URL-encoded):
```text
channel_id=your-slack-channel-id
```

