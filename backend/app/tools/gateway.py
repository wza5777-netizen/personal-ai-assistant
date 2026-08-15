"""Tool Gateway: executes tools through the registry with logging and gating.

The gateway routes tool calls to registered tools, logs every invocation for
audit, and enforces a human-approval gate for ``HIGH`` risk tools: when such a
tool is requested, an :class:`Approval` row is created and an
:class:`ApprovalRequired` exception is raised to pause the agent until a human
approves or rejects the request.

Every tool execution is bounded by :data:`TOOL_TIMEOUT_SECONDS` so a slow or
hung tool can never stall the agent run; on timeout the gateway returns a safe
error string (never raises), preserving the existing ``execute_tool`` contract.
"""
import asyncio
import json
import time
from contextvars import ContextVar
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.observability import logger
from app.observability.tracking import redact_for_logging
from app.repositories.approval_repository import ApprovalRepository
from app.tools.base import BaseTool, RiskLevel
from app.tools.registry import ToolRegistry, registry as default_registry

#: Context variable holding the DB session active for the current agent run,
#: so the gateway can persist approval requests without threading the session
#: through every node call.
_db_session: ContextVar[Optional[AsyncSession]] = ContextVar("db_session", default=None)

#: Maximum wall-clock time (seconds) a single tool execution may take. Tools
#: that exceed this bound are cancelled and surface a ``tool_timeout`` error
#: instead of stalling the agent run. Centralized here so it is easy to tune.
TOOL_TIMEOUT_SECONDS = 10


def set_db_session(session: Optional[AsyncSession]) -> None:
    """Register the active DB session for the current agent run (or clear)."""
    _db_session.set(session)


class ApprovalRequired(Exception):
    """Raised by the gateway when a HIGH-risk tool requires human approval.

    The agent loop should catch this and pause (return an ``approval_required``
    status) rather than continuing to call tools.
    """

    def __init__(self, approval: Approval) -> None:
        self.approval = approval
        super().__init__(f"approval required for tool '{approval.tool_name}'")


class ToolGateway:
    """Routes tool calls to registered tools and logs each invocation."""

    def __init__(self, registry: ToolRegistry = default_registry) -> None:
        self.registry = registry

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict,
        user_id: str = "",
        db: Optional[AsyncSession] = None,
        conversation_id: Optional[str] = None,
    ) -> str:
        """Execute a tool by name and return its string result.

        Logs tool_name, arguments, duration, and result around the call.
        On unknown tool or error, returns a safe error string (never raises).

        For HIGH-risk tools, when a DB session is available (explicitly or via
        the run context var), an approval request is created and
        :class:`ApprovalRequired` is raised to pause the agent.
        """
        start = time.perf_counter()
        logger.info("tool_call_start", tool=tool_name, user_id=user_id, arguments=redact_for_logging(arguments or {}))
        try:
            tool: Optional[BaseTool] = self.registry.get_tool(tool_name)
            if tool is None:
                result = f"Error: unknown tool '{tool_name}'"
            elif tool.risk_level == RiskLevel.HIGH:
                session = db or _db_session.get()
                if session is not None:
                    # Gate HIGH-risk tools behind human approval; pause agent.
                    repo = ApprovalRepository(session)
                    approval = await repo.create(
                        user_id=user_id,
                        tool_name=tool_name,
                        arguments=json.dumps(arguments or {}, ensure_ascii=False),
                        conversation_id=conversation_id,
                    )
                    logger.info(
                        "approval_created",
                        approval_id=approval.id,
                        tool=tool_name,
                        user_id=user_id,
                    )
                    raise ApprovalRequired(approval)
                result = await self._run_with_timeout(tool, arguments, user_id, tool_name)
            else:
                result = await self._run_with_timeout(tool, arguments, user_id, tool_name)
        except ApprovalRequired:
            raise
        except asyncio.TimeoutError:
            # Should not normally reach here (helper swallows timeouts), but be
            # defensive so a timeout can never crash the agent.
            logger.error("tool_timeout_outer", tool=tool_name, timeout=TOOL_TIMEOUT_SECONDS)
            result = "Error: tool timeout"
        except Exception as exc:  # noqa: BLE001 - gateway must not crash the agent
            result = f"Error executing tool '{tool_name}': {exc}"
        duration_ms = (time.perf_counter() - start) * 1000.0
        logger.info(
            "tool_call_end",
            tool=tool_name,
            user_id=user_id,
            duration_ms=round(duration_ms, 2),
            result=result,
        )
        return result

    async def _run_with_timeout(
        self,
        tool: BaseTool,
        arguments: dict,
        user_id: str,
        tool_name: str,
    ) -> str:
        """Execute a tool bounded by :data:`TOOL_TIMEOUT_SECONDS`.

        Works for both ``async`` and ``sync`` tool implementations (``sync``
        tools are still invoked through the ``async def execute`` interface).
        On timeout the task is cancelled and a safe ``"Error: tool timeout"``
        string is returned so the agent run continues; no exception escapes.
        """
        try:
            return await asyncio.wait_for(
                tool.execute(arguments or {}, user_id=user_id),
                timeout=TOOL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(
                "tool_timeout",
                tool=tool_name,
                timeout=TOOL_TIMEOUT_SECONDS,
            )
            return "Error: tool timeout"


# Singleton gateway.
gateway = ToolGateway()
