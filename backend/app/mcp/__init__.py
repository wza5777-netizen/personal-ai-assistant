"""MCP architecture package.

Provides the building blocks for MCP-compatible tool providers without
connecting to any real MCP server:

* :class:`MCPClient` / :class:`MockMCPClient` - the client interface.
* :func:`adapt_mcp_result` - MCP envelope -> :class:`ToolResult`.
* :class:`MCPToolDefinition` / :class:`MCPToolRegistry` - tool metadata.
"""
from app.mcp.adapter import adapt_mcp_result
from app.mcp.client import MCPCallResult, MCPClient, MCPToolSpec, MockMCPClient
from app.mcp.registry import (
    MCPToolDefinition,
    MCPToolRegistry,
    mcp_registry,
    register_mcp_tool,
    list_mcp_tools,
    get_mcp_tool,
)

__all__ = [
    "MCPClient",
    "MCPToolSpec",
    "MCPCallResult",
    "MockMCPClient",
    "adapt_mcp_result",
    "MCPToolDefinition",
    "MCPToolRegistry",
    "mcp_registry",
    "register_mcp_tool",
    "list_mcp_tools",
    "get_mcp_tool",
]
