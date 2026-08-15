"""Admin observability endpoints: list and inspect agent runs + trace timelines."""
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.observability import logger
from app.repositories.run_repository import RunRepository
from app.schemas.run import (
    RunDetail,
    RunListResponse,
    RunSummary,
    ToolCallView,
    TraceEventView,
)
from app.security.auth import verify_admin_token

router = APIRouter(prefix="/api/v1/admin", tags=["admin-observability"])


def _summarize(run, metric) -> RunSummary:
    return RunSummary(
        run_id=run.id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        latency_ms=run.latency_ms,
        llm_calls=metric.llm_calls if metric else 0,
        tool_calls=metric.tool_calls if metric else 0,
        tool_failures=metric.tool_failures if metric else 0,
        input_tokens=metric.input_tokens if metric else 0,
        output_tokens=metric.output_tokens if metric else 0,
        total_tokens=metric.total_tokens if metric else 0,
        estimated_cost_usd=round(metric.estimated_cost_usd, 6) if metric and metric.estimated_cost_usd is not None else None,
        model=metric.model if metric else None,
        usage_available=metric.usage_available if metric else True,
    )


def _parse_details(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


@router.get("/runs", response_model=RunListResponse)
async def list_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by run status"),
    conversation_id: Optional[str] = Query(None, description="Filter by conversation id"),
    _: dict = Depends(verify_admin_token),
    session: AsyncSession = Depends(get_session),
) -> RunListResponse:
    repo = RunRepository(session)
    runs = await repo.list_runs(limit=limit, offset=offset, status=status, conversation_id=conversation_id)
    total = await repo.count_runs(status=status, conversation_id=conversation_id)
    summaries = []
    for run in runs:
        metric = await repo.get_metric(run.id)
        summaries.append(_summarize(run, metric))
    return RunListResponse(total=total, limit=limit, offset=offset, runs=summaries)


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    _: dict = Depends(verify_admin_token),
    session: AsyncSession = Depends(get_session),
) -> RunDetail:
    repo = RunRepository(session)
    run = await repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    metric = await repo.get_metric(run_id)
    events = await repo.list_events(run_id)

    timeline: list[TraceEventView] = []
    tool_calls_detail: list[ToolCallView] = []
    for ev in events:
        timeline.append(
            TraceEventView(
                sequence=ev.sequence,
                event_type=ev.event_type,
                timestamp=ev.timestamp,
                tool_name=ev.tool_name,
                status=ev.status,
                details=_parse_details(ev.details),
            )
        )
        if ev.event_type == "tool_call":
            details = _parse_details(ev.details) or {}
            tool_calls_detail.append(
                ToolCallView(
                    sequence=ev.sequence,
                    tool_name=ev.tool_name or details.get("tool", "unknown"),
                    status=ev.status,
                    arguments=details.get("arguments"),
                )
            )
        elif ev.event_type == "tool_result":
            details = _parse_details(ev.details) or {}
            # Attach result success to the most recent preceding tool_call entry.
            for tc in reversed(tool_calls_detail):
                if tc.tool_name == (ev.tool_name or details.get("tool")):
                    tc.result_ok = details.get("ok")
                    if tc.status is None:
                        tc.status = ev.status
                    break

    logger.info("admin_run_inspected", run_id=run_id)
    return RunDetail(
        run_id=run.id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        latency_ms=run.latency_ms,
        prompt=run.prompt,
        final_response=run.final_response,
        error=run.error,
        llm_calls=metric.llm_calls if metric else 0,
        tool_calls=metric.tool_calls if metric else 0,
        tool_failures=metric.tool_failures if metric else 0,
        input_tokens=metric.input_tokens if metric else 0,
        output_tokens=metric.output_tokens if metric else 0,
        total_tokens=metric.total_tokens if metric else 0,
        estimated_cost_usd=round(metric.estimated_cost_usd, 6) if metric and metric.estimated_cost_usd is not None else None,
        model=metric.model if metric else None,
        usage_available=metric.usage_available if metric else True,
        timeline=timeline,
        tool_calls_detail=tool_calls_detail,
    )


@router.post("/token", summary="Issue an admin JWT (dev convenience)")
async def issue_token() -> dict:
    """Issue a short-lived admin token. Requires ``JWT_SECRET`` to be configured.

    In production, obtain the token out-of-band; this endpoint is a convenience.
    """
    from app.security.auth import create_admin_token

    token = create_admin_token()
    return {"access_token": token, "token_type": "bearer"}
