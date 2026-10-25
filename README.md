# meeting-chat

A FastAPI service for multi-turn Q&A over past meetings. It uses a Google ADK agent that looks up data in meeting-processor.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in GOOGLE_API_KEY
uvicorn app.main:app --reload --port 8001
```

meeting-processor must be running on `MEETING_PROCESSOR_URL` (default `http://localhost:8000`) for the agent's tools to work.

Run tests (no Google key or meeting-processor needed; the agent is mocked):

```bash
python -m pytest tests/ -v
```

## API

| Method | Path                 | Description                                                   |
|--------|----------------------|---------------------------------------------------------------|
| POST   | `/chat`              | Send a message (`{session_id, message}`) and get `{session_id, response}`. Rate limited to 20/minute per IP. |
| DELETE | `/chat/{session_id}` | Delete the session's history. Returns 204, or 404 if the session is unknown. |
| GET    | `/health`            | Liveness check                                                |

Reuse the same `session_id` for follow-up questions. The agent sees the earlier turns, so "Who agreed to it?" resolves against the previous answer.

## Design decisions

- **No database.** meeting-chat stores no meeting data. Its three tools (`list_meetings`, `get_meeting`, `search_meetings`) call meeting-processor's REST API, so meeting-processor stays the only source of truth.
- **In-memory sessions.** Conversation history lives in ADK's `InMemorySessionService`, created once per process. History is lost on restart and is not shared across workers, so run a single worker for now.
- **Client-side search.** meeting-processor has no search endpoint yet. `search_meetings` fetches every meeting and substring-matches the title and analysis, which is fine for small histories but scales linearly.
- **No auth yet.** Every caller uses one ADK user (`anonymous`), so anyone who knows a `session_id` can read or delete that conversation.

## Not here

- A2A (agent-to-agent) interface
- Streaming responses
- Deployment
