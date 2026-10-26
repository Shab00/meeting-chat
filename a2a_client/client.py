"""A2A client for meeting-processor's analyse_meeting skill.

Self-contained (reads its own env var, no app imports) so it can be copied
between services unchanged.
"""

import asyncio
import json
import logging
import os

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_artifact_text, get_message_text, new_text_message
from a2a.types import Role, SendMessageRequest, TaskState

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60.0


def _base_url() -> str:
    # Read per call so tests / .env loading after import still take effect.
    return os.environ.get("MEETING_PROCESSOR_A2A_URL", "http://localhost:8000")


async def _analyse(transcript: str, base_url: str) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
        card = await A2ACardResolver(http, base_url).get_agent_card()
        # Non-streaming: the server replies once with the finished Task, so
        # there are no stream events to stitch together.
        client = await create_client(
            card, client_config=ClientConfig(streaming=False, httpx_client=http)
        )
        request = SendMessageRequest(
            message=new_text_message(transcript, role=Role.ROLE_USER)
        )
        task = None
        async for event in client.send_message(request):
            if event.HasField("task"):
                task = event.task
            elif event.HasField("message"):
                raise RuntimeError(
                    f"A2A agent replied with a message, not a task: "
                    f"{get_message_text(event.message)}"
                )

    if task is None:
        raise RuntimeError("A2A agent returned no task")
    if task.status.state != TaskState.TASK_STATE_COMPLETED:
        detail = get_message_text(task.status.message) if task.status.message else ""
        raise RuntimeError(
            f"A2A task {task.id} ended in {TaskState.Name(task.status.state)}: {detail}"
        )
    if not task.artifacts:
        raise RuntimeError(f"A2A task {task.id} completed with no artifact")

    logger.info("A2A task %s completed via %s", task.id, base_url)
    return json.loads(get_artifact_text(task.artifacts[0]))


async def analyse_via_a2a(transcript: str) -> dict:
    """Analyse a transcript via meeting-processor's A2A server.

    Returns the MeetingAnalysis as a dict with "summary", "action_items",
    "decisions" and "risks". Raises RuntimeError on any failure.
    """
    base_url = _base_url()
    logger.info("A2A analyse_meeting -> %s (%d chars)", base_url, len(transcript))
    try:
        return await asyncio.wait_for(_analyse(transcript, base_url), TIMEOUT_SECONDS)
    except RuntimeError:
        raise
    except asyncio.TimeoutError as e:
        raise RuntimeError(f"A2A call to {base_url} timed out after {TIMEOUT_SECONDS}s") from e
    except Exception as e:
        raise RuntimeError(f"A2A call to {base_url} failed: {e!r}") from e
