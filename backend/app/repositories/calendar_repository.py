"""Calendar repository: data-access layer for events."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event


class CalendarRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_event(
        self,
        *,
        user_id: str,
        title: str,
        start_time: datetime,
        end_time: datetime,
        description: Optional[str] = None,
        status: str = "scheduled",
    ) -> Event:
        event = Event(
            user_id=user_id,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            status=status,
        )
        self.session.add(event)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(event)
        return event

    async def list_events(
        self,
        *,
        user_id: str,
        start_from: Optional[datetime] = None,
        start_to: Optional[datetime] = None,
    ) -> List[Event]:
        stmt = select(Event).where(Event.user_id == user_id)
        if start_from is not None:
            stmt = stmt.where(Event.start_time >= start_from)
        if start_to is not None:
            stmt = stmt.where(Event.start_time <= start_to)
        stmt = stmt.order_by(Event.start_time.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_event(self, *, event_id: int, user_id: str) -> Optional[Event]:
        stmt = select(Event).where(Event.id == event_id, Event.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_event(
        self,
        *,
        event: Event,
        title: Optional[str] = None,
        description: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> Event:
        if title is not None:
            event.title = title
        if description is not None:
            event.description = description
        if start_time is not None:
            event.start_time = start_time
        if end_time is not None:
            event.end_time = end_time
        if status is not None:
            event.status = status
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(event)
        return event

    async def find_overlapping(
        self,
        *,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
        exclude_event_id: Optional[int] = None,
    ) -> List[Event]:
        """Find events that overlap the given time window."""
        stmt = select(Event).where(
            Event.user_id == user_id,
            Event.start_time < end_time,
            Event.end_time > start_time,
        )
        if exclude_event_id is not None:
            stmt = stmt.where(Event.id != exclude_event_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
