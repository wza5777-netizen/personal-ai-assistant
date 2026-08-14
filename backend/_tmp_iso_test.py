"""Temp verify identity isolation: client-supplied user_id is never trusted."""
import asyncio
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.database.session import Base
from app.models import conversation, message, user  # noqa: F401
from app.repositories.conversation_repository import get_messages, get_recent_conversation
from fastapi.testclient import TestClient
from app.main import app

ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
Session = async_sessionmaker(bind=ENGINE, class_=AsyncSession, expire_on_commit=False)

DEFAULT_USER_ID = "default-user"


async def seed():
    async with ENGINE.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[user.User.__table__, conversation.Conversation.__table__, message.Message.__table__],
        )
    async with Session() as s:
        # A conversation owned by the default user
        c = conversation.Conversation(id="conv-A", user_id=DEFAULT_USER_ID, title="A")
        s.add(c)
        s.add(message.Message(id=uuid.uuid4().hex, conversation_id="conv-A", role="user", content="secret"))
        await s.commit()


async def main():
    await seed()
    import app.repositories.conversation_repository as repo
    repo.AsyncSessionLocal = Session  # route repository to the test SQLite session

    # --- Test 1: owner (current_user_id = DEFAULT_USER_ID) reads OK ---
    msgs = await get_messages("conv-A", DEFAULT_USER_ID)
    assert len(msgs) == 1 and msgs[0].content == "secret", msgs
    print("TEST 1 (owner read): OK ->", len(msgs), "msg")

    # --- Test 2: a different current_user_id cannot read User A's conversation ---
    msgs_b = await get_messages("conv-A", "some-other-user")
    assert msgs_b == [], "Isolation broken: non-owner got data"
    print("TEST 2 (non-owner blocked): OK -> empty")

    # Non-existent conversation also empty for anyone
    assert await get_messages("nope", DEFAULT_USER_ID) == []
    print("TEST 2b (unknown conv): OK -> empty")

    # --- Test 3: HTTP layer — no user_id query param accepted; uses server identity ---
    import app.repositories.conversation_repository as repo
    repo.AsyncSessionLocal = Session

    with TestClient(app) as client:
        # The endpoint must NOT take user_id from query (would 422 or ignore).
        # Hit without any user_id param; server resolves identity internally.
        r = client.get("/api/v1/conversations/conv-A/messages")
        assert r.status_code == 200, r.text
        assert r.json()[0]["content"] == "secret"
        # Confirm no 'user_id' accepted: sending a forged one must be ignored
        # (FastAPI would reject unknown query params -> 422 if it were declared).
        r2 = client.get("/api/v1/conversations/conv-A/messages?user_id=attacker")
        assert r2.status_code == 200, r2.text  # accepted but ignored (no such param declared)
        assert r2.json()[0]["content"] == "secret"  # still owner's data, attacker param ignored
        print("TEST 3 (no client user_id / forged ignored): OK -> server identity used")

    print("\nALL ISOLATION CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
