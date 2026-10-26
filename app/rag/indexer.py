import logging
import uuid

import httpx
from langchain_core.documents import Document

from app.config import settings
from app.rag.store import get_store

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0)

# Meeting IDs indexed by this process. Empty on startup, so the first sync_all
# re-embeds every meeting (one OpenAI call each). That's acceptable at this
# scale. Rows don't duplicate because each meeting is stored under a
# deterministic row id and PGVectorStore upserts on that id (see _row_id).
_indexed_ids: set[str] = set()


def _row_id(meeting_id: str) -> str:
    """Stable vector-row id for a meeting, so re-indexing upserts in place.

    The table's id column is UUID-typed. Real meeting ids are UUIDs already;
    anything else is mapped deterministically with uuid5.
    """
    try:
        return str(uuid.UUID(meeting_id))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"meeting:{meeting_id}"))


def _meeting_to_document(meeting: dict) -> Document:
    """Combine meeting fields into one searchable text blob.

    One document per meeting: semantic search does better on one coherent
    chunk than on fragmented per-section docs.
    """
    title = meeting.get("title", "")
    analysis = meeting.get("analysis") or {}
    parts = [f"Meeting: {title}"]
    if analysis.get("summary"):
        parts.append(f"Summary: {analysis['summary']}")
    for ai in analysis.get("action_items", []) or []:
        parts.append(
            f"Action item: {ai.get('task')} assigned to {ai.get('owner')}"
            + (f" due {ai['due_date']}" if ai.get("due_date") else "")
        )
    for d in analysis.get("decisions", []) or []:
        parts.append(f"Decision: {d.get('description')}")
    for r in analysis.get("risks", []) or []:
        parts.append(f"Risk: {r.get('description')}")
    return Document(
        page_content="\n".join(parts),
        metadata={
            "meeting_id": str(meeting.get("id")),
            "title": title,
        },
    )


async def index_meeting(meeting: dict) -> None:
    """Embed one meeting. Skips if already indexed in this process."""
    mid = str(meeting.get("id"))
    if mid in _indexed_ids:
        return
    doc = _meeting_to_document(meeting)
    await get_store().aadd_documents([doc], ids=[_row_id(mid)])
    _indexed_ids.add(mid)
    log.info("Indexed meeting %s", mid)


async def sync_all() -> dict:
    """Pull all meetings from meeting-processor and index any missing."""
    indexed = skipped = failed = 0
    async with httpx.AsyncClient(
        base_url=settings.meeting_processor_url, timeout=TIMEOUT
    ) as client:
        r = await client.get("/meetings")
        r.raise_for_status()
        summaries = r.json()

        for s in summaries:
            mid = str(s.get("id"))
            if mid in _indexed_ids:
                skipped += 1
                continue
            try:
                rd = await client.get(f"/meetings/{mid}")
                rd.raise_for_status()
                await index_meeting(rd.json())
                indexed += 1
            except Exception as e:
                log.warning("Failed to index meeting %s: %s", mid, e)
                failed += 1

    return {
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "total": len(summaries),
    }
