from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.rag.indexer import sync_all
from app.rag.store import init_table
from app.routes import chat, index


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_table()
        result = await sync_all()
        print(
            f"[startup] indexed {result['indexed']} meetings, "
            f"skipped {result['skipped']}, failed {result['failed']}"
        )
    except Exception as e:
        # Don't crash if meeting-processor or the vector DB is down; call
        # POST /index once both are up.
        print(f"[startup] index sync failed: {e!r}")
    yield


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
