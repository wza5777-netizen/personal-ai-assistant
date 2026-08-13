"""Streaming event bus for the agent.

The agent emits structured events (``agent_start``, ``tool_call``,
``tool_result``, ``token``, ``agent_end``) while it runs. Consumers (the SSE
endpoint) register an async callback via a :mod:`contextvars` context variable
so that the LangGraph nodes — which have no direct reference to the request —
can push events out in real time.
"""
import json
import time
import uuid
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Optional

from app.observability import logger

#: Signature of the event callback. ``event`` is the dict payload to stream.
EventCallback = Callable[[dict], Awaitable[None]]

#: Context variable holding the active emitter callback (or ``None``).
_stream_sink: ContextVar[Optional[EventCallback]] = ContextVar("stream_sink", default=None)

#: Optional agent-run id, used to correlate all events of one run.
_run_id: ContextVar[Optional[str]] = ContextVar("run_id", default=None)


def set_stream_sink(callback: Optional[EventCallback]) -> None:
    """Register (or clear, with ``None``) the event callback for this context."""
    _stream_sink.set(callback)


def get_stream_sink() -> Optional[EventCallback]:
    return _stream_sink.get()


def set_run_id(run_id: Optional[str]) -> None:
    _run_id.set(run_id)


def get_run_id() -> Optional[str]:
    return _run_id.get()


async def emit(event_type: str, data: dict[str, Any]) -> None:
    """Emit a stream event to the registered sink, if any.

    Fails silently if no sink is registered or the sink raises.
    """
    sink = _stream_sink.get()
    if sink is None:
        return
    payload = {
        "type": event_type,
        "run_id": _run_id.get(),
        "timestamp": time.time(),
        **data,
    }
    try:
        await sink(payload)
    except Exception as exc:  # noqa: BLE001 - never break the agent on emit errors
        logger.warning("stream_emit_failed", error=str(exc))


def new_run_id() -> str:
    return uuid.uuid4().hex


def to_sse(payload: dict[str, Any]) -> str:
    """Serialize a payload into a Server-Sent Events ``data:`` frame."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
