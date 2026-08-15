"""Memory repository: data-access layer for memories."""
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import Memory


@dataclass
class MemoryHit:
    """A memory returned by semantic search, with its similarity score."""

    memory: Memory
    similarity: float


class MemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_memory(
        self,
        *,
        user_id: str,
        content: str,
        type: str = "general",
        importance: int = 1,
        embedding: Optional[list[float]] = None,
    ) -> Memory:
        memory = Memory(
            user_id=user_id,
            content=content,
            type=type,
            importance=importance,
            embedding=embedding,
        )
        self.session.add(memory)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(memory)
        return memory

    async def search_memories(
        self,
        *,
        user_id: str,
        query_embedding: list[float],
        limit: int = 5,
        memory_type: Optional[str] = None,
    ) -> List[MemoryHit]:
        """Semantic (pgvector cosine-distance) search scoped to the user.

        Only memories belonging to ``user_id`` are considered (strict user
        isolation). When ``memory_type`` is provided, results are further
        filtered by type. Rows without an embedding are excluded because they
        cannot be ranked by similarity.
        """
        distance = Memory.embedding.cosine_distance(query_embedding)
        stmt = (
            select(Memory, distance.label("distance"))
            .where(Memory.user_id == user_id)
            .where(Memory.embedding.isnot(None))
        )
        if memory_type is not None:
            stmt = stmt.where(Memory.type == memory_type)
        # pgvector cosine_distance: smaller == more similar. 1 - distance == cosine similarity.
        stmt = stmt.order_by(distance).limit(limit)
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            MemoryHit(memory=row[0], similarity=round(1.0 - float(row[1]), 4))
            for row in rows
        ]

    async def list_memories(
        self, *, user_id: str, type: Optional[str] = None
    ) -> List[Memory]:
        stmt = select(Memory).where(Memory.user_id == user_id)
        if type is not None:
            stmt = stmt.where(Memory.type == type)
        stmt = stmt.order_by(Memory.updated_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_null_embeddings(self, *, limit: int = 200) -> List[Memory]:
        """Return memories whose embedding has not been computed yet."""
        stmt = (
            select(Memory)
            .where(Memory.embedding.is_(None))
            .order_by(Memory.id)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_embedding(self, *, memory_id: int, embedding: list[float]) -> None:
        """Persist a computed embedding for a memory (used by backfill)."""
        stmt = (
            select(Memory).where(Memory.id == memory_id)
        )
        result = await self.session.execute(stmt)
        memory = result.scalar_one_or_none()
        if memory is None:
            return
        memory.embedding = embedding
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
