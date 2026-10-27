from typing import Any

import httpx

from a2a_client import analyse_via_a2a
from app.config import settings

TIMEOUT = httpx.Timeout(180.0)


async def _get(path: str) -> Any:
    async with httpx.AsyncClient(
        base_url=settings.meeting_processor_url, timeout=TIMEOUT
    ) as client:
        r = await client.get(path)
        r.raise_for_status()
        return r.json()


async def list_meetings() -> list[dict]:
    """List all past meetings, newest first.

    Returns only lightweight metadata; call get_meeting for the full analysis.

    Returns:
        A list of meetings, each with keys "id", "title" and "created_at".
    """
    return await _get("/meetings")


async def get_meeting(meeting_id: str) -> dict:
    """Get one meeting with its full analysis.

    Args:
        meeting_id: The meeting's UUID, as returned by list_meetings or
            search_meetings.

    Returns:
        The meeting with keys "id", "title", "created_at" and "analysis". The
        analysis holds "summary", "action_items", "decisions" and "risks".
        If the meeting does not exist, returns {"error": "..."} instead.
    """
    try:
        return await _get(f"/meetings/{meeting_id}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (404, 422):
            return {"error": f"No meeting found with id {meeting_id}"}
        raise


async def search_meetings(query: str, k: int = 3) -> list[dict]:
    """Search past meetings by meaning using semantic similarity.

    This is SEMANTIC search, not keyword search: it finds meetings whose
    content means the same thing as the query even when no words overlap
    (e.g. "ad spend" matches a meeting about "marketing spend").

    Use this when the user refers to a meeting by topic, decision, person's
    responsibility or concept rather than an exact title or date. Pass the
    user's question (or its key idea) as the query; do not reduce it to a
    single keyword. Call get_meeting with a result's meeting_id for full
    details.

    Examples of good queries:
        "what did we decide about ad spend"
        "who is responsible for the hiring plan"
        "any risks around revenue"

    Args:
        query: A natural-language description of what to find.
        k: How many meetings to return (default 3).

    Returns:
        Up to k meetings, most similar first, each with "meeting_id",
        "title" and "snippet" (the start of the indexed text).
    """
    from app.rag.store import get_store

    # asimilarity_search exists in langchain-postgres 0.0.19, so no sync
    # fallback is needed; the async call keeps the event loop free.
    results = await get_store().asimilarity_search(query, k=k)
    # ADK doesn't log tool calls by default; this makes them visible in the
    # uvicorn console.
    print(f"[tool] search_meetings({query!r}, k={k}) -> {len(results)} results")
    return [
        {
            "meeting_id": r.metadata.get("meeting_id"),
            "title": r.metadata.get("title"),
            "snippet": r.page_content[:400],
        }
        for r in results
    ]


async def analyse_meeting_a2a(transcript: str) -> dict:
    """Analyse a NEW meeting transcript via meeting-processor's A2A agent.

    Use this when the user pastes a raw transcript and wants it analysed.
    The result is not saved as a past meeting, so it will not show up in
    list_meetings or search_meetings afterwards.

    Args:
        transcript: The full meeting transcript text (100-50,000 chars).

    Returns:
        The analysis with keys "summary", "action_items", "decisions" and
        "risks". On failure, returns {"error": "..."} instead.
    """
    print(f"[tool] analyse_meeting_a2a({len(transcript)} chars)")
    try:
        return await analyse_via_a2a(transcript)
    except RuntimeError as e:
        return {"error": str(e)}
