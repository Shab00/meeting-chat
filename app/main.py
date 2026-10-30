import asyncio
import litellm

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.rag.indexer import sync_all
from app.rag.store import init_table
from app.routes import chat, index


SYNC_ATTEMPTS = 6
SYNC_RETRY_DELAY_S = 30

ALLOWED_ORIGINS = {
    "https://shab00.github.io",
    "http://localhost:4000",
}


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


# ---- CORS FIX ----
# This middleware runs at the outermost layer and MUST be added before
# CORSMiddleware so it executes last on the response path, overwriting
# any header mutations that happen below it.
#
# Why this is needed here and not in meeting-processor:
#   /chat is decorated with @limiter.limit(...) from slowapi. slowapi
#   wraps the route and its rate-limit handler strips some response
#   headers, including Access-Control-Allow-Origin. The result is a
#   200 response with `access-control-allow-credentials: true` but no
#   allow-origin header, which the browser rejects as a CORS failure.
#
# The middleware below handles OPTIONS directly (short-circuiting the
# route entirely) and sets the required headers on all responses from
# known origins. Vary: Origin prevents Cloudflare (which sits in front
# of *.onrender.com) from caching a preflight response for the wrong
# origin.
@app.middleware("http")
async def _force_cors(request: Request, call_next):
    origin = request.headers.get("origin", "")

    # Short-circuit the preflight — never let slowapi or CORSMiddleware
    # see an OPTIONS request on /chat.
    if request.method == "OPTIONS" and origin in ALLOWED_ORIGINS:
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
                "Access-Control-Max-Age": "600",
                "Vary": "Origin",
            },
        )

    response = await call_next(request)

    # Overwrite on the real response. Runs after every route handler,
    # after slowapi, after CORSMiddleware — last writer wins.
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Vary"] = "Origin"

    return response
# ---- END CORS FIX ----


# Standard CORSMiddleware. Kept for non-/chat routes (index, health) and
# as a fallback if the middleware above is ever removed. Adding it AFTER
# the custom middleware means it runs first on the response path, so the
# custom middleware above always gets the last word.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=600,
)

app.include_router(chat.router)
app.include_router(index.router)


@app.get("/health")
def health():
    return {"status": "ok"}
