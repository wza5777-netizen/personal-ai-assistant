"""Integration tests for semantic Memory retrieval (pgvector).

These tests exercise the full pipeline: embedding generation -> pgvector
similarity search -> top-K hits, plus strict per-user isolation.

They require a live PostgreSQL instance (with the pgvector extension) and a
working embedding endpoint configured via .env. When the DB is unreachable the
tests are skipped instead of failing the suite.

Run with a real DB:
    cd backend && pytest tests/test_memory_retrieval.py -v
"""
from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# These tests require a live PostgreSQL + pgvector + embedding endpoint. When the
# suite is configured for the offline SQLite auth tests (DATABASE_URL points at
# sqlite), skip them instead of failing.
pytestmark = pytest.mark.skipif(
    "sqlite" in os.environ.get("DATABASE_URL", ""),
    reason="requires live PostgreSQL + pgvector",
)

from app.database.session import engine
from app.infrastructure.embedding import embed_text
from app.models.memory import Memory
from app.repositories.memory_repository import MemoryRepository
from app.services.memory_service import MemoryService

# Use a dedicated engine with NullPool so connections are never shared/reused
# across awaits (avoids asyncpg "another operation is in progress").
_test_engine = create_async_engine(engine.url, poolclass=NullPool, future=True)
TestSession = async_sessionmaker(_test_engine, expire_on_commit=False)

TEST_USER_A = "retrieval-test-user-a"
TEST_USER_B = "retrieval-test-user-b"


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def _seed(session, user_id: str, content: str, mtype: str) -> None:
    repo = MemoryRepository(session)
    vec = embed_text(content)
    await repo.create_memory(
        user_id=user_id, content=content, type=mtype, importance=5, embedding=vec
    )


async def _cleanup(session) -> None:
    from sqlalchemy import delete

    await session.execute(
        delete(Memory).where(Memory.user_id.in_([TEST_USER_A, TEST_USER_B]))
    )
    await session.commit()


@pytest.mark.asyncio
async def test_semantic_recall_preferences():
    async with TestSession() as session:
        await _cleanup(session)
        await _seed(session, TEST_USER_A, "用户喜欢 Python 编程语言", "preference")

        service = MemoryService(MemoryRepository(session))
        queries = [
            "我的喜好是什么？",
            "我喜欢什么语言？",
            "我的编程偏好是什么？",
            "平时更喜欢使用哪种开发语言？",
        ]
        for q in queries:
            hits = await service.search_memories(user_id=TEST_USER_A, query=q, limit=5)
            contents = [h.memory.content for h in hits]
            assert any("Python" in c for c in contents), (
                f"query={q!r} failed to recall the Python memory; got {contents!r}"
            )
        await _cleanup(session)


@pytest.mark.asyncio
async def test_semantic_recall_habit():
    async with TestSession() as session:
        await _cleanup(session)
        await _seed(session, TEST_USER_A, "用户习惯晚上8点以后学习", "habit")

        service = MemoryService(MemoryRepository(session))
        hits = await service.search_memories(
            user_id=TEST_USER_A, query="我一般什么时候学习？", limit=5
        )
        contents = [h.memory.content for h in hits]
        assert any("学习" in c for c in contents), (
            f"failed to recall habit; got {contents!r}"
        )
        await _cleanup(session)


@pytest.mark.asyncio
async def test_user_isolation():
    async with TestSession() as session:
        await _cleanup(session)
        # User A owns the Python memory; User B must never see it.
        await _seed(session, TEST_USER_A, "用户喜欢 Python 编程语言", "preference")

        service = MemoryService(MemoryRepository(session))
        hits = await service.search_memories(
            user_id=TEST_USER_B, query="我的编程偏好是什么？", limit=5
        )
        assert len(hits) == 0, (
            f"User B leaked User A memory: {[h.memory.content for h in hits]!r}"
        )
        await _cleanup(session)


@pytest.mark.asyncio
async def test_memory_type_filter():
    async with TestSession() as session:
        await _cleanup(session)
        await _seed(session, TEST_USER_A, "用户喜欢 Python 编程语言", "preference")
        await _seed(session, TEST_USER_A, "用户每天跑步锻炼", "habit")

        service = MemoryService(MemoryRepository(session))
        hits = await service.search_memories(
            user_id=TEST_USER_A, query="我的偏好", limit=5, memory_type="preference"
        )
        assert len(hits) >= 1
        assert all(h.memory.type == "preference" for h in hits)
        await _cleanup(session)
