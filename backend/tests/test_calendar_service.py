"""Tests for the Calendar service conflict detection (no DB required)."""
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.models.event import Event
from app.schemas.event import EventCreate, EventUpdate
from app.services.calendar_service import CalendarService, EventConflictError

USER_ID = "u1"


def _event(**kw) -> Event:
    defaults = dict(
        id=1,
        user_id=USER_ID,
        title="已有会议",
        description=None,
        start_time=datetime(2026, 8, 13, 9, 0),
        end_time=datetime(2026, 8, 13, 10, 0),
        status="scheduled",
    )
    defaults.update(kw)
    return Event(**defaults)


@pytest.mark.asyncio
async def test_create_no_conflict():
    repo = AsyncMock()
    repo.find_overlapping.return_value = []
    repo.create_event.return_value = _event()
    service = CalendarService.__new__(CalendarService)
    service.repo = repo

    payload = EventCreate(
        title="新会议",
        start_time=datetime(2026, 8, 13, 11, 0),
        end_time=datetime(2026, 8, 13, 12, 0),
    )
    result = await service.create_event(USER_ID, payload)
    assert result.title == "已有会议"
    repo.create_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_overlap_rejected():
    repo = AsyncMock()
    repo.find_overlapping.return_value = [_event()]
    service = CalendarService.__new__(CalendarService)
    service.repo = repo

    payload = EventCreate(
        title="撞车会议",
        start_time=datetime(2026, 8, 13, 9, 30),
        end_time=datetime(2026, 8, 13, 10, 30),
    )
    with pytest.raises(EventConflictError):
        await service.create_event(USER_ID, payload)
    repo.create_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_reschedule_conflict_rejected():
    existing = _event(id=7)
    repo = AsyncMock()
    repo.get_event.return_value = existing
    repo.find_overlapping.return_value = [_event(id=9, title="另一个会议")]
    service = CalendarService.__new__(CalendarService)
    service.repo = repo

    payload = EventUpdate(
        start_time=datetime(2026, 8, 13, 9, 30),
        end_time=datetime(2026, 8, 13, 10, 30),
    )
    with pytest.raises(EventConflictError):
        await service.update_event(USER_ID, 7, payload)
    repo.update_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_no_conflict():
    existing = _event(id=7)
    repo = AsyncMock()
    repo.get_event.return_value = existing
    repo.find_overlapping.return_value = []
    repo.update_event.return_value = existing
    service = CalendarService.__new__(CalendarService)
    service.repo = repo

    payload = EventUpdate(title="改名")
    result = await service.update_event(USER_ID, 7, payload)
    assert result.title == "已有会议"
    repo.update_event.assert_awaited_once()
