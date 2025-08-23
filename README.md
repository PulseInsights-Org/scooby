# Scooby - Meeting Bot Server

Scooby is a meeting bot server that provides real-time meeting assistance and information retrieval capabilities.

## Features

- Real-time meeting bot integration via WebSocket
- Gemini Live API integration for AI-powered responses
- Vector search using Pinecone
- Graph database queries using Neo4j
- HTTP endpoint for text-based queries (`/query`)

## Installation

1. **Clone the repository and navigate to the scooby directory:**
   ```bash
   cd scooby
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   Create a `.env` file in the scooby directory with:
   ```
   PINECONE_API_KEY=your_pinecone_api_key_here
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=your_password
   ```

## Running the Server

### Start the Scooby server:
```bash
python -m app.main
```

The server will start on `http://localhost:8000` by default.

### Available Endpoints

- **GET `/`** - Bot HTML interface
- **POST `/query`** - Text-based query endpoint for retrieval
- **POST `/add_scooby`** - Add Scooby bot to a meeting
- **WebSocket `/ws`** - Real-time meeting connection

## Testing

### Test the query endpoint:
```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the main events discussed?"}'
```

### Test the bot interface:
Open `http://localhost:8000` in your browser to access the bot interface.

## Troubleshooting

- **Import errors**: Make sure all dependencies are installed with `pip install -r requirements.txt`
