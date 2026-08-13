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

    @abstractmethod
    async def execute(self, arguments: dict, user_id: str = "") -> str:
        """Run the tool and return a string result.

        Args:
            arguments: arguments supplied by the LLM tool call.
            user_id: id of the user that triggered the call (for auditing).
        """
        raise NotImplementedError
