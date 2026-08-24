"""Tool implementations served by the time MCP server.

These are plain functions returning structured data. They are registered with
the MCP server (see ``server.py``) and invoked over stdio by the
:class:`StdioMCPClient`.
"""
from datetime import datetime, timezone


def get_current_time() -> dict:
    """Return the current date/time as a structured payload.

    Returns:
        A JSON-serializable dict with ``datetime`` (ISO-8601 UTC) and
        ``timezone`` fields, e.g.::

            {"datetime": "2026-08-15T12:34:56+00:00", "timezone": "UTC"}
    """
    now = datetime.now(timezone.utc)
    return {
        "datetime": now.isoformat(),
        "timezone": "UTC",
    }
