from fastapi import APIRouter

from app.rag.indexer import sync_all

router = APIRouter(tags=["index"])


@router.post("/index")
async def trigger_index():
    """Pull meetings from meeting-processor and index any missing ones."""
    return await sync_all()
