"""create_task / list_tasks tools."""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.database.session import AsyncSessionLocal
from app.schemas.task import TaskCreate
from app.services.task_service import TaskService
from app.tools.base import BaseTool, RiskLevel
from app.tools.registry import registry


class CreateTaskTool(BaseTool):
    name = "create_task"
    description = (
        "Create a new task for the current user. "
        "Use this when the user wants to add, record, or remember a todo / task."
    )
    risk_level = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "任务标题"},
            "description": {"type": "string", "description": "任务描述（可选）"},
            "due_time": {
                "type": "string",
                "description": "截止时间，ISO 8601 格式，例如 2026-08-13T10:00:00",
            },
        },
        "required": ["title"],
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        title = arguments.get("title")
        if not title:
            return json.dumps({"error": "title is required"}, ensure_ascii=False)

        due_time_value = arguments.get("due_time")
        due_time: Optional[datetime] = None
        if due_time_value:
            if isinstance(due_time_value, datetime):
                due_time = due_time_value
            else:
                due_time = datetime.fromisoformat(str(due_time_value))

        payload = TaskCreate(
            title=title,
            description=arguments.get("description"),
            due_time=due_time,
        )

        async with AsyncSessionLocal() as session:
            service = TaskService(session)
            task = await service.create_task(user_id, payload)

        return json.dumps(
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "due_time": task.due_time.isoformat() if task.due_time else None,
            },
            ensure_ascii=False,
        )


class ListTasksTool(BaseTool):
    name = "list_tasks"
    description = (
        "List the current user's tasks. "
        "Use this when the user asks about todo items, unfinished tasks, or task status. "
        "By default returns pending (unfinished) tasks."
    )
    risk_level = RiskLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["pending", "completed", "all"],
                "description": "任务状态过滤：pending（未完成，默认）、completed（已完成）、all（全部）",
            }
        },
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        status_value = arguments.get("status") if arguments else None

        status_filter: Optional[str] = None
        if status_value and str(status_value).lower() != "all":
            status_filter = str(status_value).lower()

        async with AsyncSessionLocal() as session:
            service = TaskService(session)
            tasks: List[Any] = await service.list_tasks(
                user_id=user_id, status=status_filter
            )

        result = [
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "priority": task.priority,
                "due_time": task.due_time.isoformat() if task.due_time else None,
                "created_at": task.created_at.isoformat() if task.created_at else None,
            }
            for task in tasks
        ]
        return json.dumps(
            {"count": len(result), "tasks": result},
            ensure_ascii=False,
        )


# Register the tools
registry.register(CreateTaskTool())
registry.register(ListTasksTool())
