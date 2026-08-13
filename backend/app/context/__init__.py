"""Context Builder: assembles background context for the agent.

Given a user query, it gathers:
  - relevant long-term memories (semantic / pgvector retrieval)
  - a summary of the user's recent conversation

The result is injected into the agent's system prompt before execution.
"""
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from sqlalchemy import select

from app.database.session import AsyncSessionLocal
from app.models.conversation import Conversation
from app.models.message import Message
from app.observability import logger
from app.observability import tracking
from app.repositories.memory_repository import MemoryRepository
from app.services.memory_service import MemoryService

MEMORY_LIMIT = 5
CONVERSATION_LIMIT = 10


@dataclass
class Context:
    """Structured context assembled from memories + recent conversation."""

    memories: List[Dict[str, Any]] = field(default_factory=list)
    conversation_summary: List[Dict[str, str]] = field(default_factory=list)

    def to_system_prompt(self) -> str:
        """Render the context as a system prompt block for the LLM."""
        parts: List[str] = []
        if self.memories:
            lines = [
                f"- [{m['type']}] {m['content']}（importance {m['importance']}）"
                for m in self.memories
            ]
            parts.append("以下是关于用户的长期记忆：\n" + "\n".join(lines))
        if self.conversation_summary:
            lines = [f"{m['role']}: {m['content']}" for m in self.conversation_summary]
            parts.append("以下是最近的对话记录（供参考）：\n" + "\n".join(lines))
        if not parts:
            return ""
        return (
            "你有以下背景上下文，回答用户问题时可以参考：\n\n"
            + "\n\n".join(parts)
        )


async def build_context(user_id: str, query: str) -> Context:
    """Build context for a user query: relevant memories + recent conversation."""
    start = time.perf_counter()
    memories: List[Dict[str, Any]] = []
    conversation_summary: List[Dict[str, str]] = []

    async with AsyncSessionLocal() as session:
        memory_service = MemoryService(MemoryRepository(session))
        if query:
            hits = await memory_service.search_memories(
                user_id=user_id, query=query, limit=MEMORY_LIMIT
            )
            memories = [
                {
                    "type": h.memory.type,
                    "content": h.memory.content,
                    "importance": h.memory.importance,
                    "similarity": h.similarity,
                }
                for h in hits
            ]

        # Recent conversation summary (most recent messages, chronological order).
        stmt = (
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_id)
            .order_by(Message.created_at.desc())
            .limit(CONVERSATION_LIMIT)
        )
        result = await session.execute(stmt)
        recent = list(result.scalars().all())
        recent.reverse()
        conversation_summary = [
            {"role": m.role, "content": m.content[:200]} for m in recent
        ]

    duration_ms = (time.perf_counter() - start) * 1000.0
    logger.info(
        "memory_retrieval",
        source="context_builder",
        user_id=user_id,
        query=query,
        hits=len(memories),
        conversation_messages=len(conversation_summary),
        duration_ms=round(duration_ms, 2),
    )
    # Structured trace event for the run timeline (no LLM chain-of-thought).
    await tracking.record_event(
        "memory_retrieval",
        details={
            "source": "context_builder",
            "hits": len(memories),
            "conversation_messages": len(conversation_summary),
            "duration_ms": round(duration_ms, 2),
        },
    )
    return Context(
        memories=memories, conversation_summary=conversation_summary
    )


__all__ = ["Context", "build_context"]
