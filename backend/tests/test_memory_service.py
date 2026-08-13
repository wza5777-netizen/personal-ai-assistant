"""Tests for the Memory service (no DB / no embedding API required)."""
from unittest.mock import AsyncMock, patch

import pytest

from app.models.memory import Memory
from app.schemas.memory import MemoryCreate
from app.services.memory_service import MemoryService


USER_ID = "u1"


def _memory(**kw) -> Memory:
    defaults = dict(
        id=1,
        user_id=USER_ID,
        type="preference",
        content="喜欢喝美式咖啡",
        importance=5,
    )
    defaults.update(kw)
    return Memory(**defaults)


@pytest.mark.asyncio
async def test_create_memory_delegates_to_repo_with_embedding():
    repo = AsyncMock()
    repo.create_memory.return_value = _memory(id=42, content="记住：周一开周会")
    service = MemoryService(repo)

    payload = MemoryCreate(content="记住：周一开周会", type="fact", importance=3)
    with patch("app.services.memory_service.embed_text", return_value=[0.1] * 8) as embed:
        result = await service.create_memory(USER_ID, payload)

    assert result.id == 42
    embed.assert_called_once_with("记住：周一开周会")
    repo.create_memory.assert_awaited_once()
    call = repo.create_memory.await_args.kwargs
    assert call["user_id"] == USER_ID
    assert call["content"] == "记住：周一开周会"
    assert call["type"] == "fact"
    assert call["importance"] == 3
    assert call["embedding"] == [0.1] * 8


@pytest.mark.asyncio
async def test_search_memories_builds_query_embedding_and_passes_type():
    repo = AsyncMock()
    repo.search_memories.return_value = [
        type("Hit", (), {"memory": _memory(), "similarity": 0.91})()
    ]
    service = MemoryService(repo)

    with patch("app.services.memory_service.embed_text", return_value=[0.2] * 8) as embed:
        result = await service.search_memories(
            user_id=USER_ID, query="我的喜好", limit=5, memory_type="preference"
        )

    embed.assert_called_once_with("我的喜好")
    repo.search_memories.assert_awaited_once()
    call = repo.search_memories.await_args.kwargs
    assert call["user_id"] == USER_ID
    assert call["query_embedding"] == [0.2] * 8
    assert call["limit"] == 5
    assert call["memory_type"] == "preference"
    assert result[0].similarity == 0.91


@pytest.mark.asyncio
async def test_list_memories_delegates_with_type_filter():
    repo = AsyncMock()
    repo.list_memories.return_value = [_memory()]
    service = MemoryService(repo)

    result = await service.list_memories(USER_ID, type="preference")

    assert len(result) == 1
    repo.list_memories.assert_awaited_once()
    call = repo.list_memories.await_args.kwargs
    assert call["type"] == "preference"
