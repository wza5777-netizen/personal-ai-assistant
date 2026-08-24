"""MCP result adapter: converts MCP envelopes into the existing ``ToolResult``.

The Agent Tool Gateway already normalizes every tool outcome into a
:class:`~app.tools.base.ToolResult`. MCP servers, however, return a different
envelope (``{"success": bool, "data": ..., "error": ...}``). This module is the
single translation boundary between the two worlds, so the rest of the gateway
stays MCP-agnostic.

Success envelope example::

    {"success": true, "data": {"weather": "sunny"}}

    -> ToolResult(ok=True, result={"weather": "sunny"})

Failure envelope example::

    {"success": false, "error": "rate limited"}

    -> ToolResult(ok=False, error="rate limited")
"""
from app.mcp.client import MCPCallResult


def adapt_mcp_result(result: MCPCallResult):
    """Convert a raw :class:`MCPCallResult` into a :class:`ToolResult`.

    Args:
        result: the envelope returned by an :class:`MCPClient`.

    Returns:
        A :class:`ToolResult` whose ``ok``/``result``/``error`` mirror the
        MCP envelope, with ``data`` mapped onto ``result``.
    """
    # Imported lazily to avoid an import cycle between ``app.mcp`` and
    # ``app.tools`` (the tools package imports the gateway, which imports this
    # adapter). ``ToolResult`` is part of the gateway's public contract.
    from app.tools.base import ToolResult
    """Convert a raw :class:`MCPCallResult` into a :class:`ToolResult`.

    Args:
        result: the envelope returned by an :class:`MCPClient`.

    Returns:
        A :class:`ToolResult` whose ``ok``/``result``/``error`` mirror the
        MCP envelope, with ``data`` mapped onto ``result``.
    """
    if result.success:
        return ToolResult(ok=True, result=result.data)
    return ToolResult(ok=False, error=result.error or "mcp call failed")


def adapt_mcp_tools_metadata(tools: list) -> list:  # pragma: no cover - typing helper
    """Pass-through helper kept for symmetry; metadata lives in ``registry``."""
    return tools
