"""Knowledge repository: documents + document_chunks data access."""
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_document(
        self, *, user_id: str, filename: str, content_type: str, chunk_count: int
    ) -> Document:
        doc = Document(
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            chunk_count=chunk_count,
        )
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def add_chunks(
        self,
        *,
        document_id: int,
        user_id: str,
        chunks: List[str],
        embeddings: List[List[float]],
    ) -> None:
        self.session.add_all(
            [
                DocumentChunk(
                    document_id=document_id,
                    user_id=user_id,
                    chunk_index=i,
                    content=content,
                    embedding=embedding,
                )
                for i, (content, embedding) in enumerate(zip(chunks, embeddings))
            ]
        )

    async def list_documents(self, *, user_id: str) -> List[Document]:
        stmt = (
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
