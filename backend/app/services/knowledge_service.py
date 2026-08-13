"""Knowledge service: ingest documents and list them."""
from typing import List

from app.knowledge.embedding import embed_texts
from app.knowledge.parser import parse_file
from app.knowledge.splitter import split_text
from app.models.document import Document
from app.observability import logger
from app.repositories.knowledge_repository import DocumentRepository


class KnowledgeService:
    def __init__(self, repo: DocumentRepository) -> None:
        self.repo = repo

    async def ingest(
        self, *, user_id: str, filename: str, content_type: str, data: bytes
    ) -> Document:
        """Full ingest pipeline: parse -> split -> embed -> persist."""
        kind, text = parse_file(filename, content_type, data)
        chunks = split_text(text)
        if not chunks:
            chunks = [text[:800]]
        embeddings = embed_texts(chunks)

        doc = await self.repo.create_document(
            user_id=user_id,
            filename=filename,
            content_type=kind,
            chunk_count=len(chunks),
        )
        await self.repo.add_chunks(
            document_id=doc.id,
            user_id=user_id,
            chunks=chunks,
            embeddings=embeddings,
        )
        await self.repo.session.commit()
        await self.repo.session.refresh(doc)

        logger.info(
            "embedding_created",
            document_id=doc.id,
            user_id=user_id,
            chunks=len(chunks),
        )
        return doc

    async def list_documents(self, user_id: str) -> List[Document]:
        return await self.repo.list_documents(user_id=user_id)
