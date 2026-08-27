"""create_task / list_tasks / update_task / complete_task / delete_task tools."""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.database.session import AsyncSessionLocal
from app.schemas.task import TaskCreate, TaskUpdate
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


def _parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 value into a datetime, tolerating datetime objects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class UpdateTaskTool(BaseTool):
    name = "update_task"
    description = (
        "Update an existing task for the current user (title, description, "
        "due_time, or status). Use this when the user wants to change, reschedule, "
        "or edit a task they already created. task_id comes from a previous "
        "list_tasks / create_task result."
    )
    risk_level = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer", "description": "任务的数字 ID（来自 list_tasks / create_task）"},
            "title": {"type": "string", "description": "新的任务标题（可选）"},
            "description": {"type": "string", "description": "新的任务描述（可选）"},
            "due_time": {
                "type": "string",
                "description": "新的截止时间，ISO 8601 格式，例如 2026-08-14T10:00:00（可选）",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "completed"],
                "description": "新的状态（可选）",
            },
        },
        "required": ["task_id"],
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        task_id_raw = arguments.get("task_id")
        if not isinstance(task_id_raw, (int, str)):
            return json.dumps({"error": "task_id is required and must be an integer"}, ensure_ascii=False)
        try:
            task_id = int(task_id_raw)
        except (TypeError, ValueError):
            return json.dumps({"error": "task_id is required and must be an integer"}, ensure_ascii=False)

        payload = TaskUpdate(
            title=arguments.get("title"),
            description=arguments.get("description"),
            due_time=_parse_iso(arguments.get("due_time")),
            status=arguments.get("status"),
        )

        async with AsyncSessionLocal() as session:
            service = TaskService(session)
            task = await service.update_task(user_id, task_id, payload)

        if task is None:
            return json.dumps({"error": "not_found"}, ensure_ascii=False)

        return json.dumps(
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "due_time": task.due_time.isoformat() if task.due_time else None,
            },
            ensure_ascii=False,
        )


class CompleteTaskTool(BaseTool):
    name = "complete_task"
    description = (
        "Mark an existing task as completed for the current user. "
        "Use this when the user says a task is done / finished / completed. "
        "task_id comes from a previous list_tasks / create_task result. "
        "Completing an already-completed task is a no-op (idempotent)."
    )
    risk_level = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer", "description": "任务的数字 ID（来自 list_tasks / create_task）"},
        },
        "required": ["task_id"],
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        task_id_raw = arguments.get("task_id")
        if not isinstance(task_id_raw, (int, str)):
            return json.dumps({"error": "task_id is required and must be an integer"}, ensure_ascii=False)
        try:
            task_id = int(task_id_raw)
        except (TypeError, ValueError):
            return json.dumps({"error": "task_id is required and must be an integer"}, ensure_ascii=False)

        async with AsyncSessionLocal() as session:
            service = TaskService(session)
            task = await service.complete_task(user_id, task_id)

        if task is None:
            return json.dumps({"error": "not_found"}, ensure_ascii=False)

        return json.dumps(
            {
                "id": task.id,
                "title": task.title,
                "status": task.status,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            },
            ensure_ascii=False,
        )


class DeleteTaskTool(BaseTool):
    name = "delete_task"
    description = (
        "Permanently delete an existing task for the current user. "
        "Use this when the user wants to remove / delete / drop a task. "
        "task_id comes from a previous list_tasks / create_task result."
    )
    risk_level = RiskLevel.MEDIUM
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "integer", "description": "任务的数字 ID（来自 list_tasks / create_task）"},
        },
        "required": ["task_id"],
    }

    async def execute(
        self, arguments: Dict[str, Any], user_id: Optional[str] = None
    ) -> str:
        user_id = user_id or "default-user"
        task_id_raw = arguments.get("task_id")
        if not isinstance(task_id_raw, (int, str)):
            return json.dumps({"error": "task_id is required and must be an integer"}, ensure_ascii=False)
        try:
            task_id = int(task_id_raw)
        except (TypeError, ValueError):
            return json.dumps({"error": "task_id is required and must be an integer"}, ensure_ascii=False)

        async with AsyncSessionLocal() as session:
            service = TaskService(session)
            deleted = await service.delete_task(user_id, task_id)

        if not deleted:
            return json.dumps({"error": "not_found"}, ensure_ascii=False)

        return json.dumps({"deleted": True, "id": task_id}, ensure_ascii=False)


# Register the tools
registry.register(CreateTaskTool())
registry.register(ListTasksTool())
registry.register(UpdateTaskTool())
registry.register(CompleteTaskTool())
registry.register(DeleteTaskTool())
