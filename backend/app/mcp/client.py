"""MCP client interface and transports.

This module defines:

* :class:`MCPClient` — the abstract interface the Tool Gateway depends on.
* :class:`MockMCPClient` — in-memory stand-in kept for tests / fallback.
* :class:`StdioMCPClient` — a real transport built on the official MCP SDK that
  launches an MCP server as a subprocess over stdio and proxies ``list_tools`` /
  ``call_tool`` to it.

The gateway always receives an :class:`MCPCallResult` (``success`` / ``data`` /
``error``), so the SDK-specific result shape is contained inside this module and
the rest of the app (adapter, gateway, observability) stays SDK-agnostic.
"""
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


@dataclass
class MCPToolSpec:
    """A tool as reported by an MCP server's ``list_tools``."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPCallResult:
    """Raw result returned by an MCP server's ``call_tool``.

    Normalized envelope consumed by :func:`app.mcp.adapter.adapt_mcp_result`:

    ``{"success": bool, "data": Any, "error": Optional[str]}``
    """

    success: bool
    data: Any = None
    error: str | None = None


class MCPClient(ABC):
    """Abstract MCP client interface.

    Subclasses implement the real transport. The Gateway only ever depends on
    this interface, so swapping transports does not touch routing / permission /
    observability logic.
    """

    server_name: str = "mcp"

    @abstractmethod
    async def list_tools(self) -> list[MCPToolSpec]:
        """Return the tools exposed by this MCP server."""
        raise NotImplementedError

    @abstractmethod
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPCallResult:
        """Invoke ``tool_name`` on the remote server with ``arguments``."""
        raise NotImplementedError


class MockMCPClient(MCPClient):
    """In-memory placeholder client used by tests and as a default stand-in.

    It does not connect to anything. Tools and their behaviours are registered
    at construction time so the architecture can be exercised end-to-end without
    a real MCP server.
    """

    def __init__(
        self,
        server_name: str = "mock_mcp",
        tools: list[MCPToolSpec] | None = None,
        handlers: dict[str, Any] | None = None,
    ) -> None:
        self.server_name = server_name
        self._tools = tools or []
        # ``handlers`` maps tool_name -> callable(args) -> Any (or raises).
        self._handlers = handlers or {}

    async def list_tools(self) -> list[MCPToolSpec]:
        return list(self._tools)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPCallResult:
        if tool_name not in self._handlers:
            return MCPCallResult(success=False, error=f"unknown mcp tool '{tool_name}'")
        try:
            data = self._handlers[tool_name](arguments)
            return MCPCallResult(success=True, data=data)
        except Exception as exc:  # noqa: BLE001 - surface as MCP error envelope
            return MCPCallResult(success=False, error=str(exc))


def _parse_content(data: Any) -> Any:
    """Best-effort JSON parsing of an MCP text content payload."""
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return data
    return data


class StdioMCPClient(MCPClient):
    """Real MCP client that launches a server subprocess over stdio.

    Usage::

        client = StdioMCPClient(
            server_name="time_server",
            command="python",
            args=["mcp_servers/time_server/server.py"],
        )
        await client.start_server()
        tools = await client.list_tools()
        result = await client.call_tool("current_time", {})
        await client.stop()

    It is also an async context manager::

        async with StdioMCPClient(...) as client:
            ...
    """

    def __init__(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.server_name = server_name
        self._command = command
        self._args = args or []
        self._env = env
        self._cwd = cwd
        self._session: Optional[ClientSession] = None
        self._read = None
        self._write = None
        self._proc_cm = None
        self._session_cm = None

    async def start_server(self) -> None:
        """Spawn the server subprocess and open an MCP session over stdio."""
        if self._session is not None:
            return
        # Merge with the current environment so PATH / venv are inherited.
        merged_env = {**os.environ}
        if self._env:
            merged_env.update(self._env)

        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=merged_env,
            cwd=self._cwd,
        )
        self._proc_cm = stdio_client(params)
        self._read, self._write = await self._proc_cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()

    async def stop(self) -> None:
        """Tear down the session and the server subprocess."""
        if self._session_cm is not None:
            await self._session_cm.__aexit__(None, None, None)
            self._session_cm = None
            self._session = None
        if self._proc_cm is not None:
            await self._proc_cm.__aexit__(None, None, None)
            self._proc_cm = None
        self._read = None
        self._write = None

    async def list_tools(self) -> list[MCPToolSpec]:
        if self._session is None:
            await self.start_server()
        assert self._session is not None
        response = await self._session.list_tools()
        specs: list[MCPToolSpec] = []
        for tool in response.tools:
            schema = getattr(tool, "inputSchema", None)
            specs.append(
                MCPToolSpec(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(schema) if schema else {},
                )
            )
        return specs

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPCallResult:
        if self._session is None:
            await self.start_server()
        assert self._session is not None
        try:
            response = await self._session.call_tool(tool_name, arguments or {})
        except Exception as exc:  # noqa: BLE001 - normalize SDK errors
            return MCPCallResult(success=False, error=str(exc))

        # MCP signals failure via response.isError; content carries the payload.
        if getattr(response, "isError", False):
            text = _content_to_text(response.content)
            return MCPCallResult(success=False, error=text or "mcp tool error")
        return MCPCallResult(success=True, data=_content_to_text(response.content))

    async def __aenter__(self) -> "StdioMCPClient":
        await self.start_server()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()


class StreamableHttpMCPClient(MCPClient):
    """Real MCP client that talks to a remote MCP server over Streamable HTTP.

    Built on the official MCP SDK's :func:`streamablehttp_client`. This is used
    to integrate third-party *remote* MCP servers (e.g. the official GitHub
    remote MCP server) without re-implementing their tool surface or the
    JSON-RPC transport.

    Authentication is supplied via request ``headers`` (e.g.
    ``Authorization: Bearer <token>``). The token is sourced from configuration
    only — it is never logged or embedded in exceptions.

    Usage::

        client = StreamableHttpMCPClient(
            server_name="github",
            url="https://api.githubcopilot.com/mcp/",
            headers={"Authorization": f"Bearer {token}", "X-MCP-Readonly": "true"},
            timeout=30.0,
        )
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("get_issue", {...})
        await client.close()
    """

    def __init__(
        self,
        server_name: str,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.server_name = server_name
        self._url = url
        # Headers may contain secrets (Authorization). They are NEVER logged.
        self._headers = headers or {}
        self._timeout = timeout
        self._session: Optional[ClientSession] = None
        self._read = None
        self._write = None
        self._http_cm = None
        self._session_cm = None

    async def connect(self) -> None:
        """Open the HTTP transport and initialize an MCP session."""
        if self._session is not None:
            return
        self._http_cm = streamablehttp_client(
            url=self._url,
            headers=self._headers,
            timeout=self._timeout,
        )
        self._read, self._write, _ = await self._http_cm.__aenter__()
        self._session_cm = ClientSession(self._read, self._write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()

    async def close(self) -> None:
        """Tear down the MCP session and the HTTP transport."""
        if self._session_cm is not None:
            await self._session_cm.__aexit__(None, None, None)
            self._session_cm = None
            self._session = None
        if self._http_cm is not None:
            await self._http_cm.__aexit__(None, None, None)
            self._http_cm = None
        self._read = None
        self._write = None

    async def list_tools(self) -> list[MCPToolSpec]:
        if self._session is None:
            await self.connect()
        assert self._session is not None
        response = await self._session.list_tools()
        specs: list[MCPToolSpec] = []
        for tool in response.tools:
            schema = getattr(tool, "inputSchema", None)
            specs.append(
                MCPToolSpec(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(schema) if schema else {},
                )
            )
        return specs

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPCallResult:
        if self._session is None:
            await self.connect()
        assert self._session is not None
        try:
            response = await self._session.call_tool(tool_name, arguments or {})
        except Exception as exc:  # noqa: BLE001 - normalize SDK errors
            return MCPCallResult(success=False, error=str(exc))

        if getattr(response, "isError", False):
            text = _content_to_text(response.content)
            return MCPCallResult(success=False, error=text or "mcp tool error")
        return MCPCallResult(success=True, data=_content_to_text(response.content))

    async def __aenter__(self) -> "StreamableHttpMCPClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


def _content_to_text(content: Any) -> Any:
    """Extract text from an MCP ``content`` list, else return it as-is."""
    if not isinstance(content, list):
        return content
    parts = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
    joined = "\n".join(parts) if parts else None
    return _parse_content(joined) if joined is not None else joined

