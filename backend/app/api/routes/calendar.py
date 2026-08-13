"""Calendar API routes."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.database.session import get_session
from app.schemas.event import EventOut
from app.services.calendar_service import CalendarService

router = APIRouter()


@router.get("/calendar/events", response_model=list[EventOut])
async def list_events(
    start_from: Optional[datetime] = Query(default=None, description="可选：起始时间过滤"),
    start_to: Optional[datetime] = Query(default=None, description="可选：截止时间过滤"),
    session=Depends(get_session),
) -> list[EventOut]:
    """Return the current user's calendar events."""
    user_id = "default-user"
    service = CalendarService(session)
    events = await service.list_events(
        user_id=user_id, start_from=start_from, start_to=start_to
    )
    return [EventOut.model_validate(e) for e in events]
