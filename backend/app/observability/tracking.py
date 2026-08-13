"""Lightweight run-tracking facade used by the agent and the API layer.

This module bridges the agent's ``contextvars``-based emit/run_id plumbing with
the persistent :class:`RunRepository`. It keeps the agent nodes free of DB
session plumbing: a context var carries the active :class:`AsyncSession` and
``run_id`` for the current request, and the helper methods write trace events,
metrics, and final status.

All persisted event ``details`` are fact-only (tool names, arg summaries,
token counts). LLM chain-of-thought is NEVER written here.
"""
import json
from contextvars import ContextVar
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.observability import AgentRun
from app.observability import logger
from app.repositories.run_repository import RunRepository

#: Active DB session for the current run (set by the streaming endpoint).
_db_session: ContextVar[Optional[AsyncSession]] = ContextVar("obs_db_session", default=None)
#: Active run id for the current run (mirrors context.stream run id).
_run_id: ContextVar[Optional[str]] = ContextVar("obs_run_id", default=None)

# Estimated per-1K-token cost for the configured model (USD). Used for a rough
# cost estimate; override via settings if a different model is used.
_EST_INPUT_COST_PER_1K = 0.0005
_EST_OUTPUT_COST_PER_1K = 0.0015


def set_run_context(*, session: AsyncSession, run_id: str) -> None:
    """Bind the DB session and run id for the current async context."""
    _db_session.set(session)
    _run_id.set(run_id)


def clear_run_context() -> None:
    _db_session.set(None)
    _run_id.set(None)


def current_run_id() -> Optional[str]:
    return _run_id.get()


def _repo() -> Optional[RunRepository]:
    session = _db_session.get()
    if session is None:
        return None
    return RunRepository(session)


def _safe_details(payload: dict[str, Any]) -> str:
    """Serialize an event payload to JSON, dropping anything too large."""
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = "{}"
    # Cap stored detail size to avoid blowing up the row.
    return text[:4000]


async def start_run(*, user_id: str, conversation_id: str, prompt: str | None = None) -> Optional[str]:
    """Create the AgentRun + metrics row. Returns run_id (or None if no session)."""
    repo = _repo()
    if repo is None:
        return None
    run_id = _run_id.get()
    if run_id is None:
        import uuid

        run_id = uuid.uuid4().hex
        _run_id.set(run_id)
    await repo.create_run(run_id=run_id, user_id=user_id, conversation_id=conversation_id, prompt=prompt)
    await repo.add_event(run_id=run_id, event_type="agent_start", details=_safe_details({"user_id": user_id}))
    logger.info("agent_run_started", run_id=run_id, user_id=user_id)
    return run_id


async def record_event(
    event_type: str,
    *,
    details: dict[str, Any] | None = None,
    tool_name: str | None = None,
    status: str | None = None,
) -> None:
    repo = _repo()
    run_id = _run_id.get()
    if repo is None or run_id is None:
        return
    await repo.add_event(
        run_id=run_id,
        event_type=event_type,
        details=_safe_details(details or {}),
        tool_name=tool_name,
        status=status,
    )


async def record_llm_call(*, input_tokens: int = 0, output_tokens: int = 0, model: str | None = None) -> None:
    """Increment LLM call count and token usage for the active run."""
    repo = _repo()
    run_id = _run_id.get()
    if repo is None or run_id is None:
        return
    await repo.increment_metric(run_id, llm_calls=1)
    if input_tokens or output_tokens:
        cost = (input_tokens / 1000.0) * _EST_INPUT_COST_PER_1K + (output_tokens / 1000.0) * _EST_OUTPUT_COST_PER_1K
        await repo.set_metric_tokens(
            run_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
        )
    await record_event("llm_end", details={"input_tokens": input_tokens, "output_tokens": output_tokens, "model": model})


async def record_tool_call(tool_name: str, *, arguments: dict[str, Any] | None = None) -> None:
    repo = _repo()
    run_id = _run_id.get()
    if repo is None or run_id is None:
        return
    await repo.increment_metric(run_id, tool_calls=1)
    # Redact any value whose key looks sensitive before logging.
    safe_args = _redact(arguments or {})
    await record_event("tool_call", details={"tool": tool_name, "arguments": safe_args}, tool_name=tool_name)


async def record_tool_result(tool_name: str, *, ok: bool, status: str = "success") -> None:
    repo = _repo()
    run_id = _run_id.get()
    if repo is None or run_id is None:
        return
    if not ok:
        await repo.increment_metric(run_id, tool_failures=1)
    await record_event("tool_result", details={"tool": tool_name, "ok": ok}, tool_name=tool_name, status=status)


async def record_approval_requested(tool_name: str, approval_id: str) -> None:
    await record_event(
        "approval_requested",
        details={"tool": tool_name, "approval_id": approval_id},
        tool_name=tool_name,
    )


async def finish_run(status: str, *, final_response: str | None = None, error: str | None = None) -> None:
    repo = _repo()
    run_id = _run_id.get()
    if repo is None or run_id is None:
        return
    await repo.update_run_status(run_id, status, final_response=final_response, error=error)
    await record_event("agent_end", details={"status": status, "error": (error[:500] if error else None)})
    logger.info("agent_run_finished", run_id=run_id, status=status)


_SENSITIVE_KEYS = {"password", "token", "api_key", "secret", "authorization", "apikey", "key"}


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` with sensitive values masked."""
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if any(s in str(key).lower() for s in _SENSITIVE_KEYS):
            out[key] = "***REDACTED***"
        elif isinstance(value, dict):
            out[key] = _redact(value)
        else:
            out[key] = value
    return out


def redact_for_logging(payload: dict[str, Any]) -> dict[str, Any]:
    """Public helper to redact sensitive keys from arbitrary log payloads."""
    return _redact(payload)
