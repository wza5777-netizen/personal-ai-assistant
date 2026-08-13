"""Calendar service: business logic for events, including conflict detection."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.repositories.calendar_repository import CalendarRepository
from app.schemas.event import EventCreate, EventUpdate


class EventConflictError(Exception):
    """Raised when a new/updated event overlaps an existing event."""

    def __init__(self, conflicting: Event) -> None:
        self.conflicting = conflicting
        super().__init__(
            f"时间冲突：与现有事件「{conflicting.title}」"
            f"（{conflicting.start_time:%Y-%m-%d %H:%M} - "
            f"{conflicting.end_time:%H:%M}）重叠，无法创建。"
        )


class CalendarService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = CalendarRepository(session)

    async def create_event(self, user_id: str, payload: EventCreate) -> Event:
        overlapping = await self.repo.find_overlapping(
            user_id=user_id,
            start_time=payload.start_time,
            end_time=payload.end_time,
        )
        if overlapping:
            raise EventConflictError(overlapping[0])
        return await self.repo.create_event(
            user_id=user_id,
            title=payload.title,
            description=payload.description,
            start_time=payload.start_time,
            end_time=payload.end_time,
            status=payload.status,
        )

    async def list_events(
        self,
        user_id: str,
        start_from: Optional[datetime] = None,
        start_to: Optional[datetime] = None,
    ) -> List[Event]:
        return await self.repo.list_events(
            user_id=user_id, start_from=start_from, start_to=start_to
        )

    async def update_event(
        self,
        user_id: str,
        event_id: int,
        payload: EventUpdate,
    ) -> Optional[Event]:
        event = await self.repo.get_event(event_id=event_id, user_id=user_id)
        if event is None:
            return None

        new_start = payload.start_time or event.start_time
        new_end = payload.end_time or event.end_time
        if new_end <= new_start:
            raise ValueError("end_time must be after start_time")

        # Conflict check on the new window, excluding the event itself.
        overlapping = await self.repo.find_overlapping(
            user_id=user_id,
            start_time=new_start,
            end_time=new_end,
            exclude_event_id=event_id,
        )
        if overlapping:
            raise EventConflictError(overlapping[0])

        return await self.repo.update_event(
            event=event,
            title=payload.title,
            description=payload.description,
            start_time=payload.start_time,
            end_time=payload.end_time,
            status=payload.status,
        )
