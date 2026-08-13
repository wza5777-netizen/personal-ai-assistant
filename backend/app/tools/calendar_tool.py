"""Calendar tools: query_calendar, create_event, update_event."""
import json
from datetime import datetime
from typing import Any, Dict, Optional

from app.database.session import AsyncSessionLocal
from app.schemas.event import EventCreate, EventUpdate
from app.services.calendar_service import CalendarService, EventConflictError
from app.tools.base import BaseTool, RiskLevel
from app.tools.registry import registry

_DT_FORMAT = "%Y-%m-%dT%H:%M:%S"
_DT_EXAMPLE = "2026-08-13T10:00:00"


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _event_to_dict(event) -> Dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "start_time": event.start_time.isoformat(),
        "end_time": event.end_time.isoformat(),
        "status": event.status,
    }


class QueryCalendarTool(BaseTool):
    name = "query_calendar"
    description = (
        "查询当前用户的日程安排。当用户询问日历、日程、会议安排、某天有什么安排时调用。"
        "可指定时间范围过滤。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "start_from": {
                "type": "string",
                "description": f"查询起始时间，ISO 8601，例如 {_DT_EXAMPLE}（可选）",
            },
            "start_to": {
                "type": "string",
                "description": f"查询截止时间，ISO 8601，例如 {_DT_EXAMPLE}（可选）",
            },
        },
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        start_from = _parse_dt(arguments.get("start_from"))
        start_to = _parse_dt(arguments.get("start_to"))

        async with AsyncSessionLocal() as session:
            service = CalendarService(session)
            events = await service.list_events(
                user_id=user_id, start_from=start_from, start_to=start_to
            )

        if not events:
            return json.dumps({"events": [], "message": "该时间范围内没有日程"}, ensure_ascii=False)
        return json.dumps(
            {"events": [_event_to_dict(e) for e in events]}, ensure_ascii=False
        )


class CreateEventTool(BaseTool):
    name = "create_event"
    description = (
        "为当前用户创建日程事件。当用户要添加会议、预约、提醒、日程安排时调用。"
        "start_time 与 end_time 必填，时间格式为 ISO 8601。若与已有日程时间重叠将失败。"
    )
    risk_level = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "事件标题"},
            "description": {"type": "string", "description": "事件描述（可选）"},
            "start_time": {
                "type": "string",
                "description": f"开始时间，ISO 8601，例如 {_DT_EXAMPLE}",
            },
            "end_time": {
                "type": "string",
                "description": f"结束时间，ISO 8601，例如 {_DT_EXAMPLE}",
            },
        },
        "required": ["title", "start_time", "end_time"],
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        title = arguments.get("title")
        start_time = _parse_dt(arguments.get("start_time"))
        end_time = _parse_dt(arguments.get("end_time"))
        if not title or not start_time or not end_time:
            return json.dumps(
                {"error": "title, start_time, end_time are required"}, ensure_ascii=False
            )
        if end_time <= start_time:
            return json.dumps({"error": "end_time must be after start_time"}, ensure_ascii=False)

        payload = EventCreate(
            title=title,
            description=arguments.get("description"),
            start_time=start_time,
            end_time=end_time,
        )
        try:
            async with AsyncSessionLocal() as session:
                service = CalendarService(session)
                event = await service.create_event(user_id, payload)
        except EventConflictError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        return json.dumps({"event": _event_to_dict(event)}, ensure_ascii=False)


class UpdateEventTool(BaseTool):
    name = "update_event"
    description = (
        "更新当前用户的日程事件。当用户要修改/改期/取消已有日程时调用。"
        "需提供 event_id，至少提供一项待更新的字段。若改期后与已有日程重叠将失败。"
    )
    risk_level = RiskLevel.HIGH
    parameters = {
        "type": "object",
        "properties": {
            "event_id": {"type": "integer", "description": "要更新的事件 ID"},
            "title": {"type": "string", "description": "新标题（可选）"},
            "description": {"type": "string", "description": "新描述（可选）"},
            "start_time": {
                "type": "string",
                "description": f"新开始时间，ISO 8601，例如 {_DT_EXAMPLE}（可选）",
            },
            "end_time": {
                "type": "string",
                "description": f"新结束时间，ISO 8601，例如 {_DT_EXAMPLE}（可选）",
            },
            "status": {"type": "string", "description": "新状态，如 scheduled/cancelled（可选）"},
        },
        "required": ["event_id"],
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        try:
            event_id = int(arguments.get("event_id"))
        except (TypeError, ValueError):
            return json.dumps({"error": "event_id is required"}, ensure_ascii=False)

        payload = EventUpdate(
            title=arguments.get("title"),
            description=arguments.get("description"),
            start_time=_parse_dt(arguments.get("start_time")),
            end_time=_parse_dt(arguments.get("end_time")),
            status=arguments.get("status"),
        )
        try:
            async with AsyncSessionLocal() as session:
                service = CalendarService(session)
                event = await service.update_event(user_id, event_id, payload)
        except EventConflictError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        except ValueError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        if event is None:
            return json.dumps({"error": "event not found"}, ensure_ascii=False)
        return json.dumps({"event": _event_to_dict(event)}, ensure_ascii=False)


# Register the calendar tools.
registry.register(QueryCalendarTool())
registry.register(CreateEventTool())
registry.register(UpdateEventTool())
