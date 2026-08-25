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

# ---------------------------------------------------------------------------
# Model-aware cost calculation.
# Prices come from the shared Settings (MODEL_PRICING env var), expressed as
# USD per 1M tokens. Unknown models yield ``None`` (cost "unavailable") rather
# than being guessed from another model's price.
# ---------------------------------------------------------------------------
def _load_pricing() -> dict[str, dict[str, float]]:
    """Load the MODEL_PRICING map from settings (cached per process)."""
    from app.config import parse_model_pricing, settings

    return parse_model_pricing(settings.model_pricing)


def _price_for(model: str | None) -> dict[str, float] | None:
    if not model:
        return None
    return _load_pricing().get(model)


def compute_cost(
    *,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
) -> float | None:
    """Compute USD cost for a model given token counts.

    Returns ``None`` when the model is unknown (no configured pricing) or when
    no model is given. Distinct from ``0.0`` (which means genuinely free).
    """
    price = _price_for(model)
    if price is None:
        return None
    in_per_1m = price["input_per_1m"]
    out_per_1m = price["output_per_1m"]
    cost = (input_tokens / 1_000_000.0) * in_per_1m + (output_tokens / 1_000_000.0) * out_per_1m
    return round(cost, 8)


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


async def record_llm_call(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str | None = None,
    usage_available: bool = True,
) -> None:
    """Increment LLM call count and record token usage + cost for the run.

    ``usage_available`` marks whether the provider actually returned token usage.
    When ``False`` the token counts are absent and cost is reported as ``None``
    (unavailable) — this is deliberately distinct from a genuine 0-token count.
    Cost is model-aware and sourced from configured pricing; unknown models
    also yield ``None``.
    """
    repo = _repo()
    run_id = _run_id.get()
    if repo is None or run_id is None:
        return
    await repo.increment_metric(run_id, llm_calls=1)
    if usage_available and (input_tokens or output_tokens):
        cost = compute_cost(model=model, input_tokens=input_tokens, output_tokens=output_tokens)
        await repo.set_metric_tokens(
            run_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost,
            model=model,
            usage_available=True,
        )
    else:
        # No real usage: record the model name if known, but flag usage as
        # unavailable and leave cost/pricing untouched (NULL).
        await repo.set_metric_tokens(
            run_id,
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=None,
            model=model,
            usage_available=False,
        )
    await record_event(
        "llm_end",
        details={
            "input_tokens": input_tokens if usage_available else None,
            "output_tokens": output_tokens if usage_available else None,
            "model": model,
            "usage_available": usage_available,
        },
    )


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


# Keys whose *values* must never reach logs (secrets, credentials, connection
# strings). Substring match on lowercased key names. ``database_url`` /
# ``connection`` / ``dsn`` are included so Postgres MCP connection strings are
# never echoed into observability.
_SENSITIVE_KEYS = {
    "password",
    "token",
    "api_key",
    "secret",
    "authorization",
    "apikey",
    "key",
    "database_url",
    "connection_string",
    "connection",
    "dsn",
}


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
