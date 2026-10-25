import os

# Settings() requires this at import time; dummy value, nothing connects.
os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from unittest.mock import AsyncMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.agents import chat_agent  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_chat(monkeypatch):
    mock = AsyncMock(return_value="The team cut marketing spend by 10%.")
    monkeypatch.setattr(chat_agent, "chat", mock)
    return mock


def test_chat_response_shape(client, mock_chat):
    r = client.post(
        "/chat",
        json={"session_id": "s-1", "message": "What did we decide about the budget?"},
    )
    assert r.status_code == 200
    assert r.json() == {
        "session_id": "s-1",
        "response": "The team cut marketing spend by 10%.",
    }
    mock_chat.assert_awaited_once()
    assert mock_chat.await_args.kwargs["message"] == (
        "What did we decide about the budget?"
    )


def test_chat_reuses_session_id(client, mock_chat):
    for msg in ("What did we decide about the budget?", "Who agreed to it?"):
        r = client.post("/chat", json={"session_id": "s-2", "message": msg})
        assert r.status_code == 200

    assert mock_chat.await_count == 2
    session_ids = [c.kwargs["session_id"] for c in mock_chat.await_args_list]
    user_ids = [c.kwargs["user_id"] for c in mock_chat.await_args_list]
    assert session_ids == ["s-2", "s-2"]
    assert user_ids[0] == user_ids[1]


def test_delete_unknown_session_returns_404(client):
    r = client.delete("/chat/does-not-exist")
    assert r.status_code == 404
