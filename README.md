# meeting-chat

A FastAPI service for multi-turn Q&A over past meetings. It uses a Google ADK agent that looks up data in meeting-processor.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in OPENAI_API_KEY
uvicorn app.main:app --reload --port 8001
```

meeting-processor must be running on `MEETING_PROCESSOR_URL` (default `http://localhost:8000`) for the agent's tools to work.

Semantic search also needs a pgvector Postgres at `VECTOR_DB_URL` (default `postgresql+psycopg://postgres:postgres@localhost:5433/vectordb`, psycopg3 driver, port 5433):

```bash
docker run -d --name pgvector-pg -p 5433:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=vectordb pgvector/pgvector:pg16
```

On startup the app creates the `meeting_embeddings` table if needed and indexes every meeting from meeting-processor. If meeting-processor isn't up yet, startup logs `[startup] index sync failed: ...` and carries on. Call `POST /index` once both services are running.

Run tests (no Google key or meeting-processor needed; the agent is mocked):

```bash
python -m pytest tests/ -v
```

## API

| Method | Path                 | Description                                                   |
|--------|----------------------|---------------------------------------------------------------|
| POST   | `/chat`              | Send a message (`{session_id, message}`) and get `{session_id, response}`. Rate limited to 20/minute per IP. |
| DELETE | `/chat/{session_id}` | Delete the session's history. Returns 204, or 404 if the session is unknown. |
| POST   | `/index`             | Pull meetings from meeting-processor and embed any not yet indexed by this process. Returns `{indexed, skipped, failed, total}`. |
| GET    | `/health`            | Liveness check                                                |

Reuse the same `session_id` for follow-up questions. The agent sees the earlier turns, so "Who agreed to it?" resolves against the previous answer.

## Design decisions

- **meeting-processor is the source of truth.** `list_meetings` and `get_meeting` call its REST API. The vector table only holds a derived, searchable copy that can be rebuilt with `POST /index`.
- **In-memory sessions.** Conversation history lives in ADK's `InMemorySessionService`, created once per process. History is lost on restart and is not shared across workers, so run a single worker for now.
- **Semantic search.** `search_meetings` embeds the query with OpenAI `text-embedding-3-small` and runs a pgvector similarity search via `langchain-postgres`. "Ad spend" therefore finds a meeting about "marketing spend". Each meeting becomes one document (title, summary, action items, decisions and risks), stored under a row id derived from the meeting id. Re-indexing upserts in place instead of duplicating.
- **Indexing is pull-based.** meeting-chat doesn't hear about new meetings. They're picked up at the next startup or `POST /index`. The "already indexed" set is in-process, so each fresh process re-embeds every meeting once, which is cheap at this scale. Edits to a meeting that this process has already indexed aren't picked up until restart.
- **A2A for analysing new transcripts.** `analyse_meeting_a2a` calls meeting-processor's A2A server (`MEETING_PROCESSOR_A2A_URL`, default `http://localhost:8000`) through `a2a_client/`. The prompt tells the agent to prefer it over the REST tools when the user pastes a transcript. The REST tools are unchanged and still handle stored meetings. A2A results are not saved, so they don't appear in `list_meetings`.
- **`a2a_client` is duplicated.** a2a_client is currently duplicated across meeting-chat and meeting-followup; extract to a shared package as a follow-up.
- **No auth yet.** Every caller uses one ADK user (`anonymous`), so anyone who knows a `session_id` can read or delete that conversation.

## Not here

- Streaming responses
- Deployment
