"""Memory endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import MemoryCreate, MemoryOut
from app.services.memory_service import MemoryService

router = APIRouter()


@router.get("/memories", response_model=list[MemoryOut])
async def list_memories(
    user_id: str = Query(default="default-user", description="User ID"),
    type: Optional[str] = Query(default=None, description="Filter by memory type"),
    session: AsyncSession = Depends(get_session),
) -> list[MemoryOut]:
    """List a user's memories, newest first."""
    service = MemoryService(MemoryRepository(session))
    memories = await service.list_memories(user_id=user_id, type=type)
    return [MemoryOut.model_validate(m) for m in memories]


@router.post("/memories", response_model=MemoryOut)
async def create_memory(
    payload: MemoryCreate,
    user_id: str = Query(default="default-user", description="User ID"),
    session: AsyncSession = Depends(get_session),
) -> MemoryOut:
    """Create a memory for a user."""
    service = MemoryService(MemoryRepository(session))
    memory = await service.create_memory(user_id=user_id, payload=payload)
    return MemoryOut.model_validate(memory)
