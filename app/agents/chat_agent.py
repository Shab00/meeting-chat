from dotenv import load_dotenv
load_dotenv()

from google.adk import Agent, Runner
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.genai import types as gtypes

from app.agents.tools import get_meeting, list_meetings, search_meetings

APP_NAME = "meeting-chat"

agent = Agent(
    name="meeting_chat",
    model=LiteLlm(model="openai/gpt-4o-mini"),
    instruction=(
        "You answer questions about a user's past meetings. "
        "Use the provided tools to look up meeting data. If the user "
        "refers to a meeting by nickname or partial title, use "
        "search_meetings. When a follow-up question uses a pronoun "
        "like 'they' or 'it', resolve it against the prior turn."
    ),
    tools=[list_meetings, get_meeting, search_meetings],
)

# Module-level so sessions (conversation history) persist across requests
# within one process. Lost on restart; not shared between workers.
session_service = InMemorySessionService()

runner = Runner(
    node=agent,
    app_name=APP_NAME,
    session_service=session_service,
    auto_create_session=True,
)


async def chat(session_id: str, user_id: str, message: str) -> str:
    """Send one user turn to the agent and return its text reply."""
    content = gtypes.Content(role="user", parts=[gtypes.Part(text=message)])
    texts: list[str] = []
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=content
    ):
        # Only final responses: skips tool-call events and any interim text
        # the model emits alongside a function call.
        if not event.is_final_response() or event.message is None:
            continue
        texts.extend(p.text for p in event.message.parts or [] if p.text)
    return "\n".join(texts).strip()


async def reset(session_id: str, user_id: str) -> bool:
    """Delete a session's history. Returns False if it did not exist."""
    existing = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if existing is None:
        return False
    await session_service.delete_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    return True
