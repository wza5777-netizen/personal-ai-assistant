"""Base tool interface for the Agent Tool Gateway."""
from abc import ABC, abstractmethod
from enum import Enum


class RiskLevel(str, Enum):
    """Risk classification for tools.

    - ``low``: read-only / non-destructive operations (no approval needed).
    - ``medium``: mutating but low-impact operations (no approval needed by
      default, surfaced in the timeline).
    - ``high``: potentially destructive or sensitive operations that require
      human approval before execution (the agent is paused).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolResult:
    """Unified result type returned by the Tool Gateway for every tool.

    Both native tools and MCP tools normalize their outcome into this shape,
    so the rest of the agent stack (and the adapter layer) never has to care
    which provider produced the result.

    Attributes:
        ok: whether the tool executed successfully.
        result: the tool payload on success (``None`` on failure).
        error: a human-readable error message on failure (``None`` on success).
    """

    def __init__(self, ok: bool, result: object = None, error: str | None = None) -> None:
        self.ok = ok
        self.result = result
        self.error = error

    def __repr__(self) -> str:
        if self.ok:
            return f"ToolResult(ok=True, result={self.result!r})"
        return f"ToolResult(ok=False, error={self.error!r})"

    def to_string(self) -> str:
        """Render the result as the string the gateway returns to the agent."""
        if self.ok:
            return str(self.result) if self.result is not None else ""
        return f"Error: {self.error}"


class BaseTool(ABC):
    """Unified interface that every agent tool must implement."""

    #: Unique tool name used by the LLM for tool calls.
    name: str = ""
    #: Human/LLM-readable description of what the tool does.
    description: str = ""
    #: Optional JSON Schema describing the tool arguments (OpenAI function format).
    parameters: dict | None = None
    #: Risk classification driving the human-approval flow (defaults to ``low``).
    risk_level: RiskLevel = RiskLevel.LOW
    #: Optional RBAC permission required to invoke this tool (defaults to ``None``
    #: meaning no permission gate). Enforced by the Tool Gateway for both native
    #: and MCP tools.
    required_permission: str | None = None

    @abstractmethod
    async def execute(self, arguments: dict, user_id: str = "") -> str:
        """Run the tool and return a string result.

        Args:
            arguments: arguments supplied by the LLM tool call.
            user_id: id of the user that triggered the call (for auditing).
        """
        raise NotImplementedError
