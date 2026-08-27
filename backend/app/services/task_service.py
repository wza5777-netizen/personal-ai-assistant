"""Task service: business logic for tasks."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate, TaskUpdate


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = TaskRepository(session)

    async def create_task(self, user_id: str, payload: TaskCreate) -> Task:
        return await self.repo.create_task(
            user_id=user_id,
            title=payload.title,
            description=payload.description,
            due_time=payload.due_time,
        )

    async def list_tasks(self, user_id: str, status: Optional[str] = None) -> List[Task]:
        return await self.repo.list_tasks(user_id=user_id, status=status)

    async def update_task(
        self, user_id: str, task_id: int, payload: TaskUpdate
    ) -> Optional[Task]:
        """Update a task owned by ``user_id``; returns None when not found."""
        return await self.repo.update_task(
            user_id=user_id,
            task_id=task_id,
            title=payload.title,
            description=payload.description,
            due_time=payload.due_time,
            status=payload.status,
        )

    async def complete_task(self, user_id: str, task_id: int) -> Optional[Task]:
        """Complete a task owned by ``user_id`` (idempotent); None when not found."""
        return await self.repo.complete_task(user_id=user_id, task_id=task_id)

    async def delete_task(self, user_id: str, task_id: int) -> bool:
        """Delete a task owned by ``user_id``; False when not found."""
        return await self.repo.delete_task(user_id=user_id, task_id=task_id)
