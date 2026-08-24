"""stdio MCP server exposing the ``current_time`` tool.

Run as a subprocess by the gateway's :class:`StdioMCPClient`::

    python mcp_servers/time_server/server.py

The server registers the tools defined in :mod:`tools` and serves them over the
MCP stdio transport. It performs no DB / network access — it is a self-contained
time provider migrated out of the previous native ``current_time`` tool.
"""
import sys
from pathlib import Path

# Ensure this directory is importable regardless of the subprocess working dir.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP

from tools import get_current_time

SERVER_NAME = "time_server"

mcp = FastMCP(SERVER_NAME)


@mcp.tool(
    name="current_time",
    description="Get current datetime information.",
)
def current_time_tool() -> dict:
    """MCP-exposed wrapper around :func:`get_current_time`."""
    return get_current_time()


def main() -> None:
    """Start the stdio MCP server (blocking)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
