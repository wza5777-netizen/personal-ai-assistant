"""Step 10.3-B: authenticated identity propagation + data isolation tests.

Uses an isolated file-backed SQLite DB (no Postgres/Neon). The real auth +
repository code paths run, but the LLM agent is mocked so no external calls
are made.

IMPORTANT: ``DATABASE_URL`` is redirected to SQLite BEFORE any ``app.*`` module
is imported, so ``app.database.session.engine`` is built against SQLite. No
runtime monkeypatching of the DB layer is needed.
"""
import os
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./.test_auth_isolation.db"
os.environ["JWT_SECRET"] = "test-secret-isolation"
os.environ["APP_ENV"] = "development"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings  # noqa: E402
from app.database.session import Base, engine, get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import user as _user_model  # noqa: E402,F401
from app.security import auth  # noqa: E402

settings.jwt_secret = "test-secret-isolation"

# Reuse the application's SQLite engine/session so there is exactly one DB.
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(monkeypatch):
    # DocumentChunk holds a pgvector.Vector column that sqlite cannot compile,
    # so drop it from the test metadata (Document itself has no vector column).
    from app.models.document import DocumentChunk

    Base.metadata.remove(DocumentChunk.__table__)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Mock the LLM agent so no external calls happen during tests.
    captured = {}

    async def _fake_invoke_agent(messages, user_id=None, conversation_id=None, db=None):
        captured["user_id"] = user_id
        return {"response": "ok", "approval_id": None, "error": False}

    monkeypatch.setattr("app.api.routes.chat.invoke_agent", _fake_invoke_agent)
    app.state.captured_agent_user_id = captured

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str) -> tuple[dict, str]:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecret"}
    )
    assert resp.status_code == 200
    return resp.json()["user"], resp.json()["access_token"]


# --------------------------------------------------------------------------- #
# Test 1: no JWT -> POST /chat 401
# --------------------------------------------------------------------------- #
async def test_chat_without_jwt_401(client: AsyncClient):
    resp = await client.post("/api/v1/chat", json={"message": "hi"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Test 2: User A JWT -> agent state receives user_id = A.id
# --------------------------------------------------------------------------- #
async def test_chat_propagates_user_id(client: AsyncClient):
    user_a, token_a = await _register(client, "a@example.com")
    resp = await client.post(
        "/api/v1/chat", json={"message": "hi"}, headers=_headers(token_a)
    )
    assert resp.status_code == 200
    assert app.state.captured_agent_user_id["user_id"] == user_a["id"]


# --------------------------------------------------------------------------- #
# Test 3: User B cannot read User A's conversation history
# --------------------------------------------------------------------------- #
async def test_conversation_ownership(client: AsyncClient):
    user_a, token_a = await _register(client, "a-conv@example.com")
    user_b, token_b = await _register(client, "b-conv@example.com")

    chat = await client.post(
        "/api/v1/chat", json={"message": "secret"}, headers=_headers(token_a)
    )
    conv_id = chat.json()["conversation_id"]

    # B requests A's conversation id -> does not get A's messages.
    resp_b = await client.get(
        f"/api/v1/conversations/{conv_id}/messages", headers=_headers(token_b)
    )
    assert resp_b.status_code == 200
    assert resp_b.json() == []  # safe empty result, no leakage


# --------------------------------------------------------------------------- #
# Test 4: User B cannot access User A's memories
# --------------------------------------------------------------------------- #
async def test_memory_isolation(client: AsyncClient):
    user_a, token_a = await _register(client, "a-mem@example.com")
    user_b, token_b = await _register(client, "b-mem@example.com")

    # Insert a memory row for A directly (avoids external embedding service and
    # sqlite BigInteger-autoincrement limitations in tests).
    from app.models.memory import Memory

    async with SessionLocal() as session:
        session.add(
            Memory(
                id=1,
                user_id=user_a["id"],
                content="A secret memory",
                type="general",
                importance=1,
                embedding=None,
            )
        )
        await session.commit()

    resp_b = await client.get("/api/v1/memories", headers=_headers(token_b))
    assert resp_b.status_code == 200
    assert resp_b.json() == []  # B sees nothing of A's memories


# --------------------------------------------------------------------------- #
# Test 5: User B cannot access User A's knowledge documents
# --------------------------------------------------------------------------- #
async def test_knowledge_isolation(client: AsyncClient):
    user_a, token_a = await _register(client, "a-doc@example.com")
    user_b, token_b = await _register(client, "b-doc@example.com")

    # Directly insert a document row for A (avoid large file upload in test).
    from sqlalchemy import insert

    from app.models.document import Document

    async with SessionLocal() as session:
        await session.execute(
            insert(Document).values(
                id="doc-a-1",
                user_id=user_a["id"],
                filename="a.txt",
                content_type="text/plain",
                chunk_count=0,
            )
        )
        await session.commit()

    resp_b = await client.get("/api/v1/knowledge/documents", headers=_headers(token_b))
    assert resp_b.status_code == 200
    assert resp_b.json() == []  # B sees none of A's documents


# --------------------------------------------------------------------------- #
# Test 6: User B cannot read/modify User A's tasks
# --------------------------------------------------------------------------- #
async def test_task_isolation(client: AsyncClient):
    user_a, token_a = await _register(client, "a-task@example.com")
    user_b, token_b = await _register(client, "b-task@example.com")

    from sqlalchemy import insert

    from app.models.task import Task

    async with SessionLocal() as session:
        await session.execute(
            insert(Task).values(
                id="task-a-1",
                user_id=user_a["id"],
                title="A task",
                description="",
                status="pending",
                due_time=None,
            )
        )
        await session.commit()

    resp_b = await client.get("/api/v1/tasks", headers=_headers(token_b))
    assert resp_b.status_code == 200
    assert resp_b.json() == []  # B sees none of A's tasks


# --------------------------------------------------------------------------- #
# Test 7: User B cannot read User A's calendar events
# --------------------------------------------------------------------------- #
async def test_calendar_isolation(client: AsyncClient):
    user_a, token_a = await _register(client, "a-cal@example.com")
    user_b, token_b = await _register(client, "b-cal@example.com")

    from sqlalchemy import insert

    from app.models.event import Event

    async with SessionLocal() as session:
        await session.execute(
            insert(Event).values(
                id="event-a-1",
                user_id=user_a["id"],
                title="A event",
                start_time=datetime(2026, 1, 1, 0, 0, 0),
                end_time=datetime(2026, 1, 1, 1, 0, 0),
                description=None,
            )
        )
        await session.commit()

    resp_b = await client.get("/api/v1/calendar/events", headers=_headers(token_b))
    assert resp_b.status_code == 200
    assert resp_b.json() == []  # B sees none of A's events


# --------------------------------------------------------------------------- #
# Test 8: User B GET on User A's approval -> 404 (IDOR fix)
# --------------------------------------------------------------------------- #
async def test_approval_idor_get_404(client: AsyncClient):
    user_a, token_a = await _register(client, "a-appr@example.com")
    user_b, token_b = await _register(client, "b-appr@example.com")

    from app.repositories.approval_repository import ApprovalRepository

    async with SessionLocal() as session:
        repo = ApprovalRepository(session)
        approval = await repo.create(
            user_id=user_a["id"], tool_name="danger", arguments="{}"
        )
        aid = approval.id

    resp_b = await client.get(f"/api/v1/approvals/{aid}", headers=_headers(token_b))
    assert resp_b.status_code == 404

    # Owner A can still see it.
    resp_a = await client.get(f"/api/v1/approvals/{aid}", headers=_headers(token_a))
    assert resp_a.status_code == 200
    assert resp_a.json()["id"] == aid


# --------------------------------------------------------------------------- #
# Test 9: User B decision on User A's approval -> 404, status unchanged
# --------------------------------------------------------------------------- #
async def test_approval_idor_decision_404(client: AsyncClient):
    user_a, token_a = await _register(client, "a-appr2@example.com")
    user_b, token_b = await _register(client, "b-appr2@example.com")

    from app.repositories.approval_repository import ApprovalRepository

    async with SessionLocal() as session:
        repo = ApprovalRepository(session)
        approval = await repo.create(
            user_id=user_a["id"], tool_name="danger", arguments="{}"
        )
        aid = approval.id

    resp_b = await client.post(
        f"/api/v1/approvals/{aid}/decision",
        json={"status": "approved"},
        headers=_headers(token_b),
    )
    assert resp_b.status_code == 404

    # Confirm status unchanged.
    async with SessionLocal() as session:
        repo = ApprovalRepository(session)
        still_pending = await repo.get(aid, user_id=user_a["id"])
        assert still_pending is not None
        assert still_pending.status == "pending"


# --------------------------------------------------------------------------- #
# Test 10: client-submitted user_id is ignored (cannot impersonate)
# --------------------------------------------------------------------------- #
async def test_client_user_id_ignored(client: AsyncClient):
    user_a, token_a = await _register(client, "a-imp@example.com")
    user_b, _ = await _register(client, "b-imp@example.com")

    # Even if a client somehow sends user_id in the body, it has no effect;
    # ChatRequest no longer carries the field, and the server uses token A.
    resp = await client.post(
        "/api/v1/chat",
        json={"message": "hi", "user_id": user_b["id"]},
        headers=_headers(token_a),
    )
    assert resp.status_code == 200
    # Agent received A's id, not B's.
    assert app.state.captured_agent_user_id["user_id"] == user_a["id"]


# --------------------------------------------------------------------------- #
# Test 11: ordinary user JWT cannot access admin Observability API
# --------------------------------------------------------------------------- #
async def test_user_token_cannot_access_admin_runs(client: AsyncClient):
    _, token_a = await _register(client, "a-admin@example.com")
    resp = await client.get("/api/v1/admin/runs", headers=_headers(token_a))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"
