"""Step 10.2-C: conversation-scoped run recovery + timeline ordering.

Validates the data link used by the refresh-restore feature:
  * GET /runs?conversation_id=... returns the most recent run first.
  * GET /runs/{run_id} returns the full ordered timeline + run metrics
    (model / tokens / usage_available / nullable cost).

Tests run against an in-memory SQLite DB. BigInteger autoincrement PKs are not
auto-assigned by SQLite, so we supply explicit ids (same pattern as
test_token_usage_tracking.py).
"""
import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest

pytestmark = pytest.mark.asyncio

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database.session import Base
from app.models.observability import AgentRun, TraceEvent, RunMetric
from app.repositories.run_repository import RunRepository


def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    return engine, async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def _init(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


_metric_seq = {"n": 0}


def _seed_run(session, *, run_id, conversation_id, started_offset, model="gpt-4o-mini"):
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    started = base.replace(minute=0, second=started_offset)
    finished = base.replace(minute=1, second=started_offset)
    run = AgentRun(
        id=run_id,  # AgentRun PK is the string run id.
        user_id="u1",
        conversation_id=conversation_id,
        status="success",
        started_at=started,
        finished_at=finished,
        latency_ms=1234,
        prompt="hi",
        final_response="ok",
        error=None,
    )
    session.add(run)
    _metric_seq["n"] += 1
    session.add(
        RunMetric(
            id=_metric_seq["n"],  # BigInteger autoincrement PK; explicit for SQLite.
            run_id=run_id,
            input_tokens=10,
            output_tokens=4,
            total_tokens=14,
            estimated_cost_usd=0.0001,
            model=model,
            usage_available=True,
        )
    )
    return run


async def test_list_runs_by_conversation_returns_newest_first():
    engine, SessionMaker = _make_session()
    await _init(engine)
    async with SessionMaker() as session:
        # Two runs in the same conversation, older first then newer.
        _seed_run(session, run_id="run-old", conversation_id="conv-1", started_offset=0)
        _seed_run(session, run_id="run-new", conversation_id="conv-1", started_offset=5)
        await session.commit()

        repo = RunRepository(session)
        runs = await repo.list_runs(conversation_id="conv-1", limit=1)
        assert len(runs) == 1
        # Newest first -> run-new (started at :05) ahead of run-old (:00).
        # AgentRun's string PK is `id` (not `run_id`).
        assert runs[0].id == "run-new"


async def test_get_run_returns_ordered_timeline_and_metrics():
    engine, SessionMaker = _make_session()
    await _init(engine)
    async with SessionMaker() as session:
        _seed_run(session, run_id="run-1", conversation_id="conv-1", started_offset=0)
        # Trace events out of insertion order to prove ordering by sequence.
        session.add(TraceEvent(id=1, run_id="run-1", sequence=2, event_type="tool_result", tool_name="current_time", status="success", details='{"tool": "current_time", "ok": true, "output_summary": "12:00"}'))
        session.add(TraceEvent(id=2, run_id="run-1", sequence=1, event_type="agent_start", tool_name=None, status=None, details="{}"))
        session.add(TraceEvent(id=3, run_id="run-1", sequence=3, event_type="tool_call", tool_name="current_time", status=None, details='{"tool": "current_time", "arguments": {"tz": "Asia/Shanghai"}, "risk_level": "low"}'))
        session.add(TraceEvent(id=4, run_id="run-1", sequence=4, event_type="knowledge_retrieval", tool_name=None, status=None, details='{"query": "天气", "hits": 3}'))
        session.add(TraceEvent(id=5, run_id="run-1", sequence=5, event_type="agent_end", tool_name=None, status="success", details="{}"))
        await session.commit()

        repo = RunRepository(session)
        run = await repo.get_run("run-1")
        assert run is not None
        assert run.conversation_id == "conv-1"
        assert run.latency_ms == 1234
        assert run.status == "success"

        events = await repo.list_events("run-1")
        types = [e.event_type for e in events]
        # Ordered by sequence regardless of insertion order.
        assert types == ["agent_start", "tool_result", "tool_call", "knowledge_retrieval", "agent_end"]

        metric = await repo.get_metric("run-1")
        assert metric.model == "gpt-4o-mini"
        assert metric.input_tokens == 10
        assert metric.output_tokens == 4
        assert metric.usage_available is True
        assert metric.estimated_cost_usd is not None


async def test_usage_unavailable_yields_null_cost_in_metric():
    engine, SessionMaker = _make_session()
    await _init(engine)
    async with SessionMaker() as session:
        _seed_run(session, run_id="run-u", conversation_id="conv-2", started_offset=0)
        # Override metric to simulate usage unavailable (cost NULL).
        metric = await RunRepository(session).get_metric("run-u")
        metric.usage_available = False
        metric.estimated_cost_usd = None
        metric.input_tokens = 0
        metric.output_tokens = 0
        await session.commit()

        repo = RunRepository(session)
        m = await repo.get_metric("run-u")
        assert m.usage_available is False
        assert m.estimated_cost_usd is None
