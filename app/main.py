import asyncio
import litellm

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.rag.indexer import sync_all
from app.rag.store import init_table
from app.routes import chat, index


SYNC_ATTEMPTS = 6
SYNC_RETRY_DELAY_S = 30


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(index.router)


@app.get("/health")
def health():
    return {"status": "ok"}
