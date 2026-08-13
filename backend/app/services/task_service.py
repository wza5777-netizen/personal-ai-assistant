"""Task service: business logic for tasks."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskCreate


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
