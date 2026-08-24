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
from app.observability.tracking import redact_for_logging, record_tool_call, record_tool_result
from app.repositories.approval_repository import ApprovalRepository
from app.security.permissions import check_permission, permission_denied_message
from app.tools.base import BaseTool, RiskLevel
from app.mcp.adapter import adapt_mcp_result
from app.mcp.client import MCPClient
from app.mcp.registry import get_mcp_tool, mcp_registry
from app.tools.registry import SOURCE_MCP, SOURCE_NATIVE, ToolRegistry, registry as default_registry

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
    """Routes tool calls to registered tools and logs each invocation.

    The gateway now spans two providers behind one interface:

    * **native** tools — the existing :class:`BaseTool` implementations in the
      registry, executed directly.
    * **mcp** tools — tools declared in the MCP tool registry and served by an
      injected :class:`MCPClient`. The gateway converts the MCP result envelope
      into the same :class:`ToolResult` via the adapter, so the agent sees no
      difference between the two sources.

    Permission (RBAC) and observability apply uniformly to both providers; an
    MCP tool can never bypass the gateway.
    """

    def __init__(
        self,
        registry: ToolRegistry = default_registry,
        mcp_clients: dict[str, MCPClient] | None = None,
    ) -> None:
        self.registry = registry
        #: Map of MCP ``server_name`` -> client used to serve MCP tools.
        self.mcp_clients: dict[str, MCPClient] = mcp_clients or {}

    def register_mcp_client(self, server_name: str, client: MCPClient) -> None:
        """Attach an MCP client for a given server name (called at wiring time)."""
        self.mcp_clients[server_name] = client

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict,
        user_id: str = "",
        db: Optional[AsyncSession] = None,
        conversation_id: Optional[str] = None,
        user_permissions: Optional[list[str]] = None,
    ) -> str:
        """Execute a tool by name and return its string result.

        Logs tool_name, source, arguments, duration, and result around the
        call. On unknown tool or error, returns a safe error string (never
        raises).

        For HIGH-risk native tools, when a DB session is available, an approval
        request is created and :class:`ApprovalRequired` is raised to pause the
        agent.

        Args:
            tool_name: name of the tool to invoke.
            arguments: arguments supplied by the LLM tool call.
            user_id: id of the user triggering the call (for auditing).
            db: optional explicit DB session. unknown when omitted; the run
                context var is consulted instead.
            conversation_id: optional conversation scoping for approval rows.
            user_permissions: permissions granted to the calling user; used for
                RBAC enforcement before a tool (native or MCP) is executed.
        """
        start = time.perf_counter()
        # Decide the provider up-front so observability can tag the source even
        # when the tool is unknown.
        source = self._resolve_source(tool_name)
        # For MCP tools, surface the originating server name in observability so
        # remote integrations (e.g. server_name="github") are attributable. This
        # field is never populated with secrets.
        mcp_def = get_mcp_tool(tool_name) if source == SOURCE_MCP else None
        server_name = mcp_def.server_name if mcp_def is not None else None
        logger.info(
            "tool_call_start",
            tool=tool_name,
            source=source,
            server_name=server_name,
            user_id=user_id,
            arguments=redact_for_logging(arguments or {}),
        )
        await record_tool_call(tool_name, arguments=arguments)
        try:
            if source == SOURCE_MCP:
                result = await self._execute_mcp_tool(
                    tool_name, arguments, user_id, user_permissions
                )
            else:
                result = await self._execute_native_tool(
                    tool_name, arguments, user_id, db, conversation_id, user_permissions
                )
        except ApprovalRequired:
            raise
        except asyncio.TimeoutError:
            logger.error("tool_timeout_outer", tool=tool_name, timeout=TOOL_TIMEOUT_SECONDS)
            result = "Error: tool timeout"
        except Exception as exc:  # noqa: BLE001 - gateway must not crash the agent
            result = f"Error executing tool '{tool_name}': {exc}"
        duration_ms = (time.perf_counter() - start) * 1000.0
        logger.info(
            "tool_call_end",
            tool=tool_name,
            source=source,
            server_name=server_name,
            user_id=user_id,
            duration_ms=round(duration_ms, 2),
            result=result,
        )
        return result

    def _resolve_source(self, tool_name: str) -> str:
        """Return ``"mcp"`` if the name is an MCP tool, else ``"native"``."""
        if get_mcp_tool(tool_name) is not None:
            return SOURCE_MCP
        return self.registry.get_source(tool_name)

    async def _execute_native_tool(
        self,
        tool_name: str,
        arguments: dict,
        user_id: str,
        db: Optional[AsyncSession],
        conversation_id: Optional[str],
        user_permissions: Optional[list[str]] = None,
    ) -> str:
        """Execute a native :class:`BaseTool`, preserving the existing path."""
        tool: Optional[BaseTool] = self.registry.get_tool(tool_name)
        if tool is None:
            return f"Error: unknown tool '{tool_name}'"
        # RBAC gate (shared with MCP tools). Native tools currently declare no
        # required_permission, so this is permissive until they opt in.
        required = getattr(tool, "required_permission", None)
        if not check_permission(required, user_permissions or []):
            msg = permission_denied_message(tool_name, required or "")
            await record_tool_result(tool_name, ok=False, status="permission_denied")
            return msg
        if tool.risk_level == RiskLevel.HIGH:
            session = db or _db_session.get()
            if session is not None:
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
            return await self._run_with_timeout(tool, arguments, user_id, tool_name)
        return await self._run_with_timeout(tool, arguments, user_id, tool_name)

    async def _execute_mcp_tool(
        self,
        tool_name: str,
        arguments: dict,
        user_id: str,
        user_permissions: Optional[list[str]],
    ) -> str:
        """Execute an MCP-served tool through the adapter + client.

        The flow is: look up the MCP definition -> enforce RBAC permission ->
        dispatch to the server's MCP client -> adapt the result envelope into a
        :class:`ToolResult` -> render to string. All observability/permission
        gating happens *inside* the gateway, so MCP tools cannot bypass it.
        """
        definition = get_mcp_tool(tool_name)
        if definition is None:
            return f"Error: unknown tool '{tool_name}'"

        # RBAC gate (shared with native tools).
        if not check_permission(definition.required_permission, user_permissions or []):
            msg = permission_denied_message(tool_name, definition.required_permission or "")
            await record_tool_result(tool_name, ok=False, status="permission_denied")
            return msg

        client = self.mcp_clients.get(definition.server_name)
        if client is None:
            client = mcp_registry.get_client(definition.server_name)
        if client is None:
            return f"Error: no MCP client for server '{definition.server_name}'"

        try:
            raw = await client.call_tool(tool_name, arguments or {})
        except Exception as exc:  # noqa: BLE001 - surface as a failed ToolResult
            await record_tool_result(tool_name, ok=False, status="error")
            return f"Error: mcp client failed for '{tool_name}': {exc}"

        tool_result = adapt_mcp_result(raw)
        await record_tool_result(
            tool_name, ok=tool_result.ok, status="success" if tool_result.ok else "error"
        )
        return tool_result.to_string()

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
