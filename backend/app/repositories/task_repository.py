"""Task repository: data-access layer for tasks."""
from datetime import datetime, timezone
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
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
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

    async def get_task(self, *, user_id: str, task_id: int) -> Optional[Task]:
        """Fetch a task, scoped to ``user_id`` (owner filter, prevents IDOR).

        Returns ``None`` when the task does not exist or belongs to another user.
        """
        stmt = select(Task).where(Task.id == task_id, Task.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_task(
        self,
        *,
        user_id: str,
        task_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        due_time: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> Optional[Task]:
        """Update a task owned by ``user_id``; returns ``None`` if not found."""
        existing = await self.get_task(user_id=user_id, task_id=task_id)
        if existing is None:
            return None
        if title is not None:
            existing.title = title
        if description is not None:
            existing.description = description
        if due_time is not None:
            existing.due_time = due_time
        if status is not None:
            existing.status = status
            # Restoring a task back to pending must clear its completion stamp.
            if status == "pending":
                existing.completed_at = None
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(existing)
        return existing

    async def complete_task(self, *, user_id: str, task_id: int) -> Optional[Task]:
        """Mark a task completed (idempotent), scoped to ``user_id``.

        Returns ``None`` if the task does not exist or belongs to another user.
        Re-completing an already-completed task is a no-op that returns the task
        unchanged (idempotent) and never creates a new record.
        """
        existing = await self.get_task(user_id=user_id, task_id=task_id)
        if existing is None:
            return None
        if existing.status == "completed" and existing.completed_at is not None:
            # Idempotent: already completed, return as-is without touching the row.
            return existing
        existing.status = "completed"
        existing.completed_at = datetime.now(timezone.utc)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(existing)
        return existing

    async def delete_task(self, *, user_id: str, task_id: int) -> bool:
        """Delete a task owned by ``user_id``; returns False if not found."""
        existing = await self.get_task(user_id=user_id, task_id=task_id)
        if existing is None:
            return False
        await self.session.delete(existing)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return True
