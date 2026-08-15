"""Repository for observability data: agent runs, trace events, run metrics."""
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.observability import AgentRun, RunMetric, TraceEvent


class RunRepository:
    """Data access for agent runs, their trace events, and metrics."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ----- AgentRun -------------------------------------------------------
    async def create_run(self, *, run_id: str, user_id: str, conversation_id: str, prompt: str | None = None) -> AgentRun:
        run = AgentRun(
            id=run_id,
            user_id=user_id,
            conversation_id=conversation_id,
            status="running",
            prompt=prompt,
        )
        self.session.add(run)
        # Metrics row created eagerly so counters can be incremented cheaply.
        self.session.add(RunMetric(run_id=run_id))
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(run)
        return run

    async def get_run(self, run_id: str) -> Optional[AgentRun]:
        result = await self.session.execute(select(AgentRun).where(AgentRun.id == run_id))
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        *,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        conversation_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentRun]:
        stmt = select(AgentRun)
        if user_id is not None:
            stmt = stmt.where(AgentRun.user_id == user_id)
        if status is not None:
            stmt = stmt.where(AgentRun.status == status)
        if conversation_id is not None:
            stmt = stmt.where(AgentRun.conversation_id == conversation_id)
        stmt = stmt.order_by(AgentRun.started_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        *,
        final_response: str | None = None,
        error: str | None = None,
    ) -> None:
        run = await self.get_run(run_id)
        if run is None:
            return
        run.finish(status, final_response=final_response, error=error)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def count_runs(
        self, *, user_id: Optional[str] = None, status: Optional[str] = None, conversation_id: Optional[str] = None
    ) -> int:
        stmt = select(func.count()).select_from(AgentRun)
        if user_id is not None:
            stmt = stmt.where(AgentRun.user_id == user_id)
        if status is not None:
            stmt = stmt.where(AgentRun.status == status)
        if conversation_id is not None:
            stmt = stmt.where(AgentRun.conversation_id == conversation_id)
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    # ----- TraceEvent -----------------------------------------------------
    async def add_event(
        self,
        *,
        run_id: str,
        event_type: str,
        details: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
    ) -> TraceEvent:
        # Determine the next sequence number for this run.
        seq_result = await self.session.execute(
            select(func.coalesce(func.max(TraceEvent.sequence), -1)).where(TraceEvent.run_id == run_id)
        )
        next_seq = int(seq_result.scalar_one()) + 1
        event = TraceEvent(
            run_id=run_id,
            event_type=event_type,
            sequence=next_seq,
            timestamp=datetime.now(),
            details=details,
            tool_name=tool_name,
            status=status,
        )
        self.session.add(event)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return event

    async def list_events(self, run_id: str) -> list[TraceEvent]:
        stmt = select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.sequence.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ----- RunMetric ------------------------------------------------------
    async def get_metric(self, run_id: str) -> Optional[RunMetric]:
        result = await self.session.execute(select(RunMetric).where(RunMetric.run_id == run_id))
        return result.scalar_one_or_none()

    async def increment_metric(self, run_id: str, **updates) -> None:
        metric = await self.get_metric(run_id)
        if metric is None:
            metric = RunMetric(run_id=run_id)
            self.session.add(metric)
        for field, delta in updates.items():
            # Treat a missing (None) current value as 0 so increments are safe.
            current = getattr(metric, field)
            setattr(metric, field, (current or 0) + delta)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def set_metric_tokens(
        self,
        run_id: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float | None = None,
        model: str | None = None,
        usage_available: bool | None = None,
    ) -> None:
        metric = await self.get_metric(run_id)
        if metric is None:
            metric = RunMetric(run_id=run_id)
            self.session.add(metric)
        metric.input_tokens = metric.input_tokens + input_tokens
        metric.output_tokens = metric.output_tokens + output_tokens
        metric.total_tokens = metric.input_tokens + metric.output_tokens
        # Cost: None means "unavailable" and must NOT be added to an existing value.
        # If both current and new are None, keep None; otherwise sum the numbers.
        if estimated_cost_usd is not None:
            metric.estimated_cost_usd = (metric.estimated_cost_usd or 0.0) + estimated_cost_usd
        if model is not None:
            metric.model = model
        if usage_available is not None:
            metric.usage_available = usage_available
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
