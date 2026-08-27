"""Task API routes.

Exposes the existing TaskService capabilities over REST. The service layer
owns all business logic (owner-scoped lookups, idempotent complete, etc.);
these routes are thin adapters only.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database.session import get_session
from app.models.user import User
from app.schemas.task import TaskCreate, TaskOut, TaskUpdate
from app.security.auth import get_current_user
from app.services.task_service import TaskService

router = APIRouter()


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
    )


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


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    session=Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TaskOut:
    """Create a task for the current user."""
    service = TaskService(session)
    task = await service.create_task(user_id=current_user.id, payload=payload)
    return TaskOut.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    session=Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TaskOut:
    """Partially update a task owned by the current user (404 if not found)."""
    service = TaskService(session)
    task = await service.update_task(
        user_id=current_user.id, task_id=task_id, payload=payload
    )
    if task is None:
        raise _not_found()
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
async def complete_task(
    task_id: int,
    session=Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TaskOut:
    """Mark a task completed (idempotent). 404 if the task does not exist."""
    service = TaskService(session)
    task = await service.complete_task(user_id=current_user.id, task_id=task_id)
    if task is None:
        raise _not_found()
    return TaskOut.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    session=Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a task owned by the current user (404 if not found)."""
    service = TaskService(session)
    deleted = await service.delete_task(user_id=current_user.id, task_id=task_id)
    if not deleted:
        raise _not_found()
