"""Task API routes."""
from fastapi import APIRouter, Depends, Query

from app.database.session import get_session
from app.models.user import User
from app.schemas.task import TaskOut
from app.security.auth import get_current_user
from app.services.task_service import TaskService

router = APIRouter()


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(
    status: str | None = Query(default=None, description="可选按状态过滤"),
    session=Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[TaskOut]:
    """Return the current user's tasks."""
    service = TaskService(session)
    tasks = await service.list_tasks(user_id=current_user.id, status=status)
    return [TaskOut.model_validate(t) for t in tasks]
