"""Tool registry: keeps track of available tools by name.

Every tool (native or MCP-backed) is tracked here as a :class:`BaseTool` so the
gateway can route uniformly. We additionally record a ``source`` per tool name
(``"native"`` or ``"mcp"``) so the gateway and observability layer can tell the
two providers apart while keeping the call path identical.
"""
from app.tools.base import BaseTool

#: Origin of a registered tool. Used only for routing / observability metadata.
SOURCE_NATIVE = "native"
SOURCE_MCP = "mcp"


class ToolRegistry:
    """In-memory registry of tools keyed by their ``name``."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._sources: dict[str, str] = {}

    def register(self, tool: BaseTool, source: str = SOURCE_NATIVE) -> None:
        """Register a tool instance.

        Args:
            tool: the tool instance to register.
            source: provenance of the tool, either ``SOURCE_NATIVE`` (default)
                or ``SOURCE_MCP``. Existing native tools continue to call this
                with the default, so no migration is required.
        """
        if not tool.name:
            raise ValueError("tool.name must not be empty")
        self._tools[tool.name] = tool
        self._sources[tool.name] = source

    def get_tool(self, name: str) -> BaseTool | None:
        """Return the tool with the given name, or ``None`` if missing."""
        return self._tools.get(name)

    def get_source(self, name: str) -> str:
        """Return the registered ``source`` for ``name`` (``"native"`` default)."""
        return self._sources.get(name, SOURCE_NATIVE)

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
