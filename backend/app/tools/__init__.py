"""Agent tools package.

Wires up built-in tools into the shared registry on import.
"""
from app.tools.base import BaseTool
from app.tools.calendar_tool import CreateEventTool, QueryCalendarTool, UpdateEventTool
from app.tools.current_time import CurrentTimeTool
from app.tools.gateway import ToolGateway, gateway
from app.tools.knowledge_tool import SearchKnowledgeTool
from app.tools.memory_tool import SaveMemoryTool, SearchMemoryTool
from app.tools.registry import ToolRegistry, registry
from app.tools.task_tool import CreateTaskTool, ListTasksTool

# Register built-in tools.
registry.register(CurrentTimeTool())
registry.register(CreateTaskTool())
registry.register(ListTasksTool())
registry.register(QueryCalendarTool())
registry.register(CreateEventTool())
registry.register(UpdateEventTool())
registry.register(SaveMemoryTool())
registry.register(SearchMemoryTool())
registry.register(SearchKnowledgeTool())


def get_gateway() -> ToolGateway:
    return gateway


__all__ = [
    "BaseTool",
    "ToolRegistry",
    "registry",
    "ToolGateway",
    "gateway",
    "CurrentTimeTool",
    "CreateTaskTool",
    "ListTasksTool",
    "QueryCalendarTool",
    "CreateEventTool",
    "UpdateEventTool",
    "SaveMemoryTool",
    "SearchMemoryTool",
    "SearchKnowledgeTool",
    "get_gateway",
]
