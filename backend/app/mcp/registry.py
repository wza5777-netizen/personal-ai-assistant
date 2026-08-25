"""MCP tool registry: metadata for tools served by MCP-compatible servers.

Native tools are tracked by :class:`app.tools.registry.ToolRegistry`. MCP tools
live in a separate metadata registry here, decoupling *discovery/permission
metadata* from the live MCP connection.

Each :class:`MCPToolDefinition` records:

* ``name``              - the **agent-facing / gateway-facing** tool name the agent
  invokes (globally unique, just like native tool names). For namespaced servers
  this is the prefixed name, e.g. ``github.list_commits``.
* ``remote_name``       - the **native MCP tool name** as advertised by the remote
  server, e.g. ``list_commits``. This is the name actually sent to
  ``client.call_tool(...)``. It equals ``name`` when no prefix is applied.
* ``description``       - human/LLM-readable description.
* ``server_name``       - which MCP server exposes it.
* ``required_permission`` - optional RBAC permission string enforced by the
  gateway before the call is forwarded to the MCP client.

The separation exists because a server's namespace is prefixed locally (to avoid
collisions) but the remote MCP server only knows its own native tool names. The
remote name is captured **at discovery time**, never guessed via string
splitting at execution time.

The gateway looks an MCP tool up here by ``name`` to find its server + client,
and checks ``required_permission`` exactly like it would for a native tool.

The registry also tracks running :class:`MCPClient` instances per server name.
Calling :meth:`MCPToolRegistry.discover_tools` launches each client, asks the
server for its tool list, and mirrors those into :class:`MCPToolDefinition`
entries — this is how the gateway learns about tools served by real servers.
"""
from dataclasses import dataclass, field
from typing import Optional

from app.mcp.client import MCPClient, MCPToolSpec
from app.observability import logger


@dataclass
class MCPToolDefinition:
    """Metadata describing a tool provided by an MCP-compatible server."""

    name: str
    remote_name: str = ""
    description: str = ""
    server_name: str = "mcp"
    required_permission: Optional[str] = None
    # Optional JSON-schema describing the tool arguments (OpenAI function style).
    parameters: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # When no remote name is supplied it defaults to the (already namespaced)
        # canonical name — which is correct for servers without a tool prefix.
        if not self.remote_name:
            self.remote_name = self.name


class MCPToolRegistry:
    """In-memory registry of MCP tool definitions and live clients."""

    def __init__(self) -> None:
        self._tools: dict[str, MCPToolDefinition] = {}
        #: server_name -> live client (populated by :meth:`register_server`).
        self._clients: dict[str, MCPClient] = {}
        #: server_name -> tool name prefix applied at discovery time.
        self._tool_prefixes: dict[str, str] = {}
        #: server_name -> default RBAC permission applied at discovery time.
        self._default_permissions: dict[str, str] = {}

    # -- definitions ------------------------------------------------------- #
    def register_mcp_tool(self, tool: MCPToolDefinition) -> None:
        """Register (or replace) an MCP tool definition by hand."""
        if not tool.name:
            raise ValueError("MCPToolDefinition.name must not be empty")
        self._tools[tool.name] = tool

    def get_mcp_tool(self, name: str) -> MCPToolDefinition | None:
        """Return the MCP tool definition for ``name``, or ``None``."""
        return self._tools.get(name)

    def list_mcp_tools(self) -> list[MCPToolDefinition]:
        """Return all registered MCP tool definitions."""
        return list(self._tools.values())

    def tool_schemas(self) -> list[dict]:
        """Return OpenAI-style function schemas for all MCP tools."""
        schemas = []
        for t in self._tools.values():
            function = {"name": t.name, "description": t.description}
            if t.parameters:
                function["parameters"] = t.parameters
            schemas.append({"type": "function", "function": function})
        return schemas

    # -- live clients / discovery ----------------------------------------- #
    def register_server(
        self,
        client: MCPClient,
        *,
        tool_prefix: str | None = None,
        default_permission: str | None = None,
    ) -> None:
        """Register a live MCP client under its ``server_name``.

        The client is not connected yet; call :meth:`discover_tools` to start it
        and synchronize the tool definitions it advertises.

        :param tool_prefix: when set, every tool discovered from this server is
            registered under ``f"{tool_prefix}{name}"`` to avoid name collisions
            with native tools or other MCP servers (e.g. ``github.``).
        :param default_permission: when set, every tool discovered from this
            server is tagged with this RBAC permission unless the tool already
            carries one.
        """
        self._clients[client.server_name] = client
        if tool_prefix is not None:
            self._tool_prefixes[client.server_name] = tool_prefix
        if default_permission is not None:
            self._default_permissions[client.server_name] = default_permission

    def get_client(self, server_name: str) -> MCPClient | None:
        """Return the live client for ``server_name``, or ``None``."""
        return self._clients.get(server_name)

    def list_servers(self) -> list[str]:
        """Return the names of all registered MCP servers."""
        return list(self._clients.keys())

    async def shutdown(self) -> None:
        """Close every registered MCP client and its server subprocess.

        Called from the FastAPI lifespan shutdown path. Each client is torn down
        independently so that one failing shutdown cannot block the others (or
        the rest of the application's graceful shutdown). Exceptions are logged
        but never re-raised.
        """
        for server_name, client in list(self._clients.items()):
            try:
                await client.stop()
            except Exception as exc:  # noqa: BLE001 - never block shutdown
                logger.error(
                    "mcp_server_shutdown_failed",
                    server_name=server_name,
                    error_type=type(exc).__name__,
                )
            else:
                logger.info("mcp_server_closed", server_name=server_name)
        self._clients.clear()
        self._tool_prefixes.clear()
        self._default_permissions.clear()
        # Tool definitions are derived from live clients; drop them so a restart
        # (or test re-run) does not leave stale MCP entries behind.
        self._tools.clear()

    async def discover_tools(self) -> list[MCPToolDefinition]:
        """Sync tool lists from every registered MCP client.

        For each server, ``client.list_tools()`` is queried and every returned
        :class:`MCPToolSpec` is mirrored into an :class:`MCPToolDefinition`. The
        registered tool ``name`` is prefixed with the server's ``tool_prefix``
        (if any) to prevent collisions, and ``default_permission`` (if any) is
        applied as the RBAC gate.

        Fault isolation (critical for production stability): discovery is
        *incremental and sticky*. Each server's previously discovered tools are
        only replaced when that specific server's ``list_tools()`` call
        *succeeds*. If a server fails to respond on a given pass (e.g. a stdio
        subprocess died after an earlier success, or a transient network error
        against the GitHub Remote MCP during a worker restart), the failure is
        logged and the server's **already-registered tools are kept**. This
        prevents a single failed re-discovery — which happens when the FastAPI
        lifespan re-runs on a Render worker restart — from wiping tools that
        were successfully discovered earlier, which would otherwise surface as
        ``unknown tool`` at runtime.

        Returns the definitions discovered/refreshed in *this* call.
        """
        discovered: list[MCPToolDefinition] = []
        for client in self._clients.values():
            name = client.server_name
            prefix = self._tool_prefixes.get(name)
            permission = self._default_permissions.get(name)
            try:
                specs: list[MCPToolSpec] = await client.list_tools()
            except Exception as exc:  # noqa: BLE001 - keep prior tools
                logger.error(
                    "mcp_discover_failed",
                    server_name=name,
                    error_type=type(exc).__name__,
                )
                # Preserve tools already registered for this server from a prior
                # successful discovery; do NOT clear them.
                discovered.extend(
                    t for t in self._tools.values() if t.server_name == name
                )
                continue
            # Refresh this server's tools: drop its previous entries, then add
            # the freshly discovered ones.
            for old in [k for k, t in self._tools.items() if t.server_name == name]:
                self._tools.pop(old, None)
            for spec in specs:
                registered_name = f"{prefix}{spec.name}" if prefix else spec.name
                definition = MCPToolDefinition(
                    name=registered_name,
                    # The native name the remote server knows, preserved verbatim
                    # from discovery so the gateway never has to guess it at call
                    # time via string manipulation.
                    remote_name=spec.name,
                    description=spec.description,
                    server_name=name,
                    required_permission=permission,
                    parameters=spec.input_schema,
                )
                self.register_mcp_tool(definition)
                discovered.append(definition)
        return discovered


# Singleton MCP tool registry shared across the application.
mcp_registry = MCPToolRegistry()


# Convenience module-level helpers backed by the singleton registry.
def register_mcp_tool(tool: MCPToolDefinition) -> None:
    """Register an MCP tool definition into the shared registry."""
    mcp_registry.register_mcp_tool(tool)


def get_mcp_tool(name: str) -> MCPToolDefinition | None:
    """Look up an MCP tool definition in the shared registry."""
    return mcp_registry.get_mcp_tool(name)


def list_mcp_tools() -> list[MCPToolDefinition]:
    """List all MCP tool definitions in the shared registry."""
    return mcp_registry.list_mcp_tools()

