"""Memory tools: save_memory, search_memory."""
import json
import time
from typing import Any, Dict, List, Optional

from app.database.session import AsyncSessionLocal
from app.observability import logger
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import MemoryCreate
from app.services.memory_service import MemoryService
from app.tools.base import BaseTool, RiskLevel
from app.tools.registry import registry


# Memory types understood by the system. Kept here so the tool schema /
# description can guide the LLM, but memory_type is always optional.
MEMORY_TYPES = ["preference", "habit", "goal", "fact", "experience", "general"]


def _memory_to_dict(memory) -> Dict[str, Any]:
    return {
        "id": memory.id,
        "type": memory.type,
        "content": memory.content,
        "importance": memory.importance,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }


def _hit_to_dict(hit) -> Dict[str, Any]:
    return {
        "id": hit.memory.id,
        "type": hit.memory.type,
        "content": hit.memory.content,
        "importance": hit.memory.importance,
        "similarity": hit.similarity,
    }


class SaveMemoryTool(BaseTool):
    name = "save_memory"
    description = (
        "保存一条关于用户的长期记忆。当用户透露个人信息、偏好、事实、决定，"
        "或明确要求你记住某事时调用。type 可选 preference/habit/goal/fact/experience/general。"
    )
    risk_level = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要记住的记忆内容"},
            "type": {
                "type": "string",
                "description": "记忆类型：preference/habit/goal/fact/experience/general，默认 general",
            },
            "importance": {"type": "integer", "description": "重要程度 1-10，默认 1"},
        },
        "required": ["content"],
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        content = str(arguments.get("content") or "").strip()
        if not content:
            return json.dumps({"error": "content is required"}, ensure_ascii=False)
        try:
            importance = int(arguments.get("importance") or 1)
        except (TypeError, ValueError):
            importance = 1
        importance = max(1, min(importance, 10))

        type_value = str(arguments.get("type") or "general")[:32]
        payload = MemoryCreate(
            content=content,
            type=type_value,
            importance=importance,
        )
        try:
            async with AsyncSessionLocal() as session:
                service = MemoryService(MemoryRepository(session))
                memory = await service.create_memory(user_id, payload)
        except Exception as exc:  # embedding/model failure -> report, no partial row
            logger.error(
                "save_memory_failed",
                user_id=user_id,
                type=type_value,
                error=str(exc),
            )
            return json.dumps(
                {"error": "保存记忆失败：向量生成服务不可用，请稍后重试"},
                ensure_ascii=False,
            )

        logger.info(
            "memory_saved",
            memory_id=memory.id,
            user_id=user_id,
            type=memory.type,
            importance=memory.importance,
        )
        return json.dumps({"memory": _memory_to_dict(memory)}, ensure_ascii=False)


class SearchMemoryTool(BaseTool):
    name = "search_memory"
    description = (
        "语义检索当前用户的长期记忆（基于向量相似度，而非关键词）。当需要回忆用户之前"
        "透露的偏好、习惯、目标、事实或背景信息时调用。例如用户问「我的喜好/我喜欢什么」"
        "或「我一般什么时候学习」时都应调用。若明确知道记忆类型，可传入 memory_type 以缩小范围；"
        "不确定类型时只传 query 即可，语义检索会自动匹配相关记忆。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用自然语言描述你想回忆的内容，例如「我的编程偏好」「我喜欢什么语言」",
            },
            "memory_type": {
                "type": "string",
                "description": "可选，记忆类型过滤：preference/habit/goal/fact/experience/general",
                "enum": MEMORY_TYPES,
            },
            "limit": {"type": "integer", "description": "返回条数上限，默认 5，最大 20"},
        },
        "required": ["query"],
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        query = str(arguments.get("query") or "").strip()
        if not query:
            return json.dumps({"error": "query is required"}, ensure_ascii=False)
        try:
            limit = int(arguments.get("limit") or 5)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 20))

        memory_type = arguments.get("memory_type")
        if memory_type is not None:
            memory_type = str(memory_type)[:32]

        start = time.perf_counter()
        try:
            async with AsyncSessionLocal() as session:
                service = MemoryService(MemoryRepository(session))
                hits: List = await service.search_memories(
                    user_id=user_id,
                    query=query,
                    limit=limit,
                    memory_type=memory_type,
                )
        except Exception as exc:
            logger.error(
                "search_memory_failed",
                user_id=user_id,
                query=query,
                memory_type=memory_type,
                error=str(exc),
            )
            return json.dumps(
                {"error": "记忆检索失败：向量服务不可用，请稍后重试"},
                ensure_ascii=False,
            )
        duration_ms = (time.perf_counter() - start) * 1000.0

        top_similarity = round(max((h.similarity for h in hits), default=0.0), 4)
        logger.info(
            "memory_retrieval",
            tool_name="search_memory",
            source="search_memory_tool",
            user_id=user_id,
            query=query,
            memory_type=memory_type,
            result_count=len(hits),
            top_similarity=top_similarity,
            duration_ms=round(duration_ms, 2),
        )
        if not hits:
            return json.dumps(
                {"memories": [], "message": "没有找到相关记忆"}, ensure_ascii=False
            )
        return json.dumps(
            {"memories": [_hit_to_dict(h) for h in hits]}, ensure_ascii=False
        )


# Register the memory tools.
registry.register(SaveMemoryTool())
registry.register(SearchMemoryTool())
