"""Knowledge endpoints: upload + list documents."""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.observability import logger
from app.repositories.knowledge_repository import DocumentRepository
from app.schemas.knowledge import DocumentOut
from app.services.knowledge_service import KnowledgeService

router = APIRouter()

ALLOWED_TYPES = {"application/pdf", "text/plain", "text/markdown"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/knowledge/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    user_id: str = Query(default="default-user", description="User ID"),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    """Upload a document, parse/split/embed it, and store in pgvector."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Use PDF/TXT/Markdown.",
        )
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    service = KnowledgeService(DocumentRepository(session))
    doc = await service.ingest(
        user_id=user_id,
        filename=file.filename or "upload",
        content_type=file.content_type or "",
        data=data,
    )

    logger.info(
        "document_uploaded",
        document_id=doc.id,
        user_id=user_id,
        filename=doc.filename,
        chunk_count=doc.chunk_count,
    )
    return DocumentOut.model_validate(doc)


@router.get("/knowledge/documents", response_model=list[DocumentOut])
async def list_documents(
    user_id: str = Query(default="default-user", description="User ID"),
    session: AsyncSession = Depends(get_session),
) -> list[DocumentOut]:
    """List a user's uploaded documents, newest first."""
    service = KnowledgeService(DocumentRepository(session))
    docs = await service.list_documents(user_id=user_id)
    return [DocumentOut.model_validate(d) for d in docs]
