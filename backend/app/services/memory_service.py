"""Memory service: business logic around memories."""
from typing import List, Optional

from app.infrastructure.embedding import embed_text
from app.models.memory import Memory
from app.repositories.memory_repository import MemoryHit, MemoryRepository
from app.schemas.memory import MemoryCreate


class MemoryService:
    def __init__(self, repo: MemoryRepository) -> None:
        self.repo = repo

    async def create_memory(self, user_id: str, payload: MemoryCreate) -> Memory:
        """Persist a memory together with its semantic embedding.

        The embedding is computed before any DB write. If the embedding call
        fails the exception propagates and no partial (content-only) row is
        created, per the project's error-handling policy.
        """
        embedding = embed_text(payload.content)
        return await self.repo.create_memory(
            user_id=user_id,
            content=payload.content,
            type=payload.type,
            importance=payload.importance,
            embedding=embedding,
        )

    async def search_memories(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 5,
        memory_type: Optional[str] = None,
    ) -> List[MemoryHit]:
        """Semantic search over the user's memories using pgvector."""
        query_embedding = embed_text(query)
        return await self.repo.search_memories(
            user_id=user_id,
            query_embedding=query_embedding,
            limit=limit,
            memory_type=memory_type,
        )

    async def list_memories(self, user_id: str, type: Optional[str] = None) -> List[Memory]:
        return await self.repo.list_memories(user_id=user_id, type=type)
