import asyncio
import litellm

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.rag.indexer import sync_all
from app.rag.store import init_table
from app.routes import chat, index


SYNC_ATTEMPTS = 6
SYNC_RETRY_DELAY_S = 30

ALLOWED_ORIGINS = [
    "https://shab00.github.io",
    "http://localhost:4000",
]


async def _startup_sync() -> None:
    # Retries because meeting-processor may be cold-starting (~60s on Render's
    # free tier); a failed sync leaves the vector store empty.
    for attempt in range(1, SYNC_ATTEMPTS + 1):
        try:
            await init_table()
            result = await sync_all()
            print(
                f"[startup] indexed {result['indexed']} meetings, "
                f"skipped {result['skipped']}, failed {result['failed']}"
            )
            print("indexer: sync complete")
            return
        except Exception as e:
            print(f"indexer: attempt {attempt}/{SYNC_ATTEMPTS} failed: {e!r}")
            if attempt < SYNC_ATTEMPTS:
                await asyncio.sleep(SYNC_RETRY_DELAY_S)
    # Out of retries; call POST /index once both services are up.


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run in the background so the app (and /health) is up immediately.
    sync_task = asyncio.create_task(_startup_sync())
    yield
    sync_task.cancel()


# Single Limiter instance shared with the @limiter.limit decorators.
limiter = chat.limiter
app = FastAPI(title="Meeting Chat", version="0.2.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# CORS handling
# ---------------------------------------------------------------------------
# CORSMiddleware is deliberately NOT used here. On this deployment it was
# returning 400 "Disallowed CORS origin" on preflight and serving a default
# allow_methods list instead of the configured one — the origin check was
# falling back to '*' which Starlette rejects when credentials are involved.
#
# CORS is handled in two explicit pieces instead:
#   1. @app.options("/chat") — explicit preflight response, 204 for known
#      origins, 403 for others. Runs before slowapi's @limiter.limit and
#      before any other middleware, so it cannot be shadowed.
#   2. @app.middleware("http") — attaches Access-Control-Allow-Origin to
#      every non-preflight response from known origins. Runs last on the
#      response path so nothing below it can strip the header.
# ---------------------------------------------------------------------------


@app.options("/chat")
async def chat_options(request: Request) -> Response:
    origin = request.headers.get("origin", "")
    if origin not in ALLOWED_ORIGINS:
        return Response(status_code=403, content="Origin not allowed")
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        },
    )


@app.middleware("http")
async def _attach_cors(request: Request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


app.include_router(chat.router)
app.include_router(index.router)


@app.get("/health")
def health():
    return {"status": "ok"}
