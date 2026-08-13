"""Tool registry: keeps track of available tools by name."""
from app.tools.base import BaseTool


class ToolRegistry:
    """In-memory registry of tools keyed by their ``name``."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if not tool.name:
            raise ValueError("tool.name must not be empty")
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> BaseTool | None:
        """Return the tool with the given name, or ``None`` if missing."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def tool_schemas(self) -> list[dict]:
        """Return OpenAI-style function schemas for all registered tools."""
        schemas = []
        for t in self._tools.values():
            function = {
                "name": t.name,
                "description": t.description,
            }
            if t.parameters:
                function["parameters"] = t.parameters
            schemas.append({"type": "function", "function": function})
        return schemas


# Singleton registry shared across the application.
registry = ToolRegistry()
