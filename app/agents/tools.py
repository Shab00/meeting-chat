import asyncio
import json
from typing import Any

import httpx

from app.config import settings

TIMEOUT = httpx.Timeout(10.0)


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


async def search_meetings(query: str) -> list[dict]:
    """Find meetings whose title or analysis mentions the query text.

    Use this when the user refers to a meeting by nickname, partial title or
    topic (e.g. "the budget meeting").

    This is a client-side placeholder until meeting-processor gets a real
    search endpoint: it fetches every meeting's detail and does a
    case-insensitive substring match on the title and the JSON-encoded
    analysis. Cost grows linearly with the number of meetings.

    Args:
        query: Text to look for, e.g. "budget" or "runway".

    Returns:
        Full meeting records (same shape as get_meeting) that match the
        query. Empty list if nothing matches.
    """
    needle = query.lower()
    meetings = await list_meetings()
    details = await asyncio.gather(*(get_meeting(str(m["id"])) for m in meetings))
    return [
        d
        for d in details
        if "error" not in d
        and (
            needle in (d.get("title") or "").lower()
            or needle in json.dumps(d.get("analysis")).lower()
        )
    ]
