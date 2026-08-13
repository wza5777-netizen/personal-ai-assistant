"""Task repository: data-access layer for tasks."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_task(
        self,
        *,
        user_id: str,
        title: str,
        description: Optional[str] = None,
        due_time: Optional[datetime] = None,
    ) -> Task:
        task = Task(
            user_id=user_id,
            title=title,
            description=description,
            due_time=due_time,
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def list_tasks(
        self, *, user_id: str, status: Optional[str] = None
    ) -> List[Task]:
        stmt = select(Task).where(Task.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Task.status == status)
        stmt = stmt.order_by(Task.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
