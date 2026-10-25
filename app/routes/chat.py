import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.agents import chat_agent

logger = logging.getLogger(__name__)

# Defined here (not in main.py) so the decorator below and app.state.limiter
# share one instance without a circular import.
limiter = Limiter(key_func=get_remote_address)

router = APIRouter(tags=["chat"])

# No auth yet, so every caller shares one ADK user; session_id alone
# separates conversations.
DEFAULT_USER_ID = "anonymous"


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    session_id: str
    response: str


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("20/minute")
async def post_chat(request: Request, body: ChatRequest) -> ChatResponse:
    try:
        # Called via the module so tests can patch app.agents.chat_agent.chat.
        reply = await chat_agent.chat(
            session_id=body.session_id,
            user_id=DEFAULT_USER_ID,
            message=body.message,
        )
    except Exception:
        logger.exception("chat failed for session %s", body.session_id)
        raise HTTPException(status_code=502, detail="Chat agent failed")
    return ChatResponse(session_id=body.session_id, response=reply)


@router.delete("/chat/{session_id}", status_code=204)
async def delete_chat(session_id: str) -> Response:
    # Removes the session from the in-memory store, so the next POST with this
    # session_id starts a fresh conversation. All sessions are also lost on
    # process restart, since nothing is persisted.
    if not await chat_agent.reset(session_id=session_id, user_id=DEFAULT_USER_ID):
        raise HTTPException(status_code=404, detail="Session not found")
    return Response(status_code=204)
