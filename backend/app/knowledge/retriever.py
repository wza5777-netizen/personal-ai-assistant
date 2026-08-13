"""Vector retrieval over document chunks using pgvector."""
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.embedding import embed_text
from app.models.document import DocumentChunk
from app.observability import logger


class KnowledgeRetriever:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(
        self, *, user_id: str, query: str, limit: int = 5
    ) -> list[DocumentChunk]:
        """Return the most similar chunks for a query (cosine distance)."""
        vec = embed_text(query)
        stmt = (
            select(DocumentChunk)
            .where(DocumentChunk.user_id == user_id)
            .order_by(DocumentChunk.embedding.cosine_distance(vec))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
