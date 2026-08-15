"""Step 10.2-A/B: real token usage + model-aware cost tracking tests.

These tests cover:
  * Test 1: streaming usage_metadata (present only on the final chunk) is captured.
  * Test 2: provider returns no usage -> usage_available=False (distinct from 0).
  * Test 3: two models with different prices -> different estimated_cost_usd.
  * Test 4: unknown model -> cost is None (never falls back to another model).
  * Test 5: streaming still emits tokens when no usage is present.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# Isolate pricing from any real environment for deterministic cost tests.
os.environ.pop("MODEL_PRICING", None)

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.database.session import Base
from app.models.observability import RunMetric
from app.observability import tracking
from app.repositories.run_repository import RunRepository

import pytest

pytestmark = pytest.mark.asyncio


async def _noop_record_event(*args, **kwargs):
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    return engine


async def _init_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def _fake_llm_session_factory(engine):
    SessionMaker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return SessionMaker


async def _seed_metric(session, run_id: str) -> None:
    """Pre-create the metric row with an explicit id.

    SQLite does not auto-increment a BigInteger primary key (only INTEGER
    PRIMARY KEY), so we supply the id explicitly in tests. This avoids touching
    the production model/schema while still exercising the real tracking path.
    """
    session.add(RunMetric(id=1, run_id=run_id))
    await session.commit()


# ---------------------------------------------------------------------------
# Test 1: usage_metadata only on the final chunk is captured correctly
# ---------------------------------------------------------------------------
async def test_usage_captured_from_final_chunk(monkeypatch):
    engine = _make_engine()
    await _init_db(engine)
    SessionMaker = _fake_llm_session_factory(engine)
    # Avoid SQLite BigInteger-autoincrement limitation on trace_events (not the
    # subject of this test); the metric path is what we validate here.
    monkeypatch.setattr("app.observability.tracking.record_event", _noop_record_event)
    # Configure pricing so a real cost is produced for gpt-4o-mini.
    monkeypatch.setattr(
        "app.observability.tracking._load_pricing",
        lambda: {"gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60}},
    )

    # Simulate the graph's capture loop: streamed text chunks (no usage) and a
    # final ``on_chat_model_end`` output carrying usage_metadata.
    from app.agents import graph as graph_mod
    from langchain_core.messages import AIMessage

    input_tokens = 0
    output_tokens = 0
    usage_seen = False

    # First two chunks: pure text, no usage_metadata (typical streaming).
    text_chunks = [
        graph_mod._usage_from_message(AIMessage(content="Hello ")),
        graph_mod._usage_from_message(AIMessage(content="world")),
    ]
    # Final message as the provider would attach on the end event.
    final = AIMessage(
        content="Hello world",
        usage_metadata={"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
    )
    final_capture = graph_mod._usage_from_message(final)

    for cap in text_chunks:
        assert cap is None  # mid-stream chunks carry no usage
    assert final_capture == (12, 3)

    if final_capture is not None:
        in_t, out_t = final_capture
        input_tokens += in_t
        output_tokens += out_t
        usage_seen = True

    assert usage_seen is True
    assert input_tokens == 12
    assert output_tokens == 3

    # Persist via tracking and verify the metric row.
    async with SessionMaker() as session:
        await _seed_metric(session, "run-t1")
        tracking.set_run_context(session=session, run_id="run-t1")
        await tracking.record_llm_call(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model="gpt-4o-mini",
            usage_available=True,
        )
        repo = RunRepository(session)
        metric = await repo.get_metric("run-t1")
        assert metric is not None
        assert metric.input_tokens == 12
        assert metric.output_tokens == 3
        assert metric.total_tokens == 15
        assert metric.usage_available is True
        assert metric.model == "gpt-4o-mini"
        # Cost for gpt-4o-mini (default pricing) should be a positive number.
        assert metric.estimated_cost_usd is not None and metric.estimated_cost_usd > 0


# ---------------------------------------------------------------------------
# Test 2: provider returns NO usage -> usage_available=False, not token=0
# ---------------------------------------------------------------------------
async def test_no_usage_marked_unavailable(monkeypatch):
    engine = _make_engine()
    await _init_db(engine)
    SessionMaker = _fake_llm_session_factory(engine)
    monkeypatch.setattr("app.observability.tracking.record_event", _noop_record_event)

    from app.agents import graph as graph_mod
    from langchain_core.messages import AIMessage

    # None of the chunks/messages carry usage_metadata.
    captures = [
        graph_mod._usage_from_message(AIMessage(content="hi")),
        graph_mod._usage_from_message(AIMessage(content="there")),
    ]
    usage_seen = any(c is not None for c in captures)
    assert usage_seen is False

    async with SessionMaker() as session:
        await _seed_metric(session, "run-t2")
        tracking.set_run_context(session=session, run_id="run-t2")
        # Exactly the branch the graph takes when usage_seen is False.
        await tracking.record_llm_call(
            input_tokens=0,
            output_tokens=0,
            model="gpt-4o-mini",
            usage_available=False,
        )
        repo = RunRepository(session)
        metric = await repo.get_metric("run-t2")
        assert metric is not None
        assert metric.usage_available is False
        # We must be able to distinguish "unavailable" from a genuine 0.
        assert metric.input_tokens == 0
        assert metric.output_tokens == 0
        # Cost must be NULL (unavailable), not 0.0.
        assert metric.estimated_cost_usd is None


# ---------------------------------------------------------------------------
# Test 3: two models with different prices -> different estimated_cost_usd
# ---------------------------------------------------------------------------
async def test_model_aware_cost_differs(monkeypatch):
    # Configure two models with clearly different prices.
    pricing = {
        "cheap-model": {"input_per_1m": 0.10, "output_per_1m": 0.20},
        "pricey-model": {"input_per_1m": 10.0, "output_per_1m": 30.0},
    }
    monkeypatch.setattr(
        "app.observability.tracking._load_pricing",
        lambda: pricing,
    )

    cost_cheap = tracking.compute_cost(model="cheap-model", input_tokens=1000, output_tokens=1000)
    cost_pricey = tracking.compute_cost(model="pricey-model", input_tokens=1000, output_tokens=1000)

    # cheap: (1000/1e6)*0.10 + (1000/1e6)*0.20 = 0.0001 + 0.0002 = 0.0003
    # pricey: (1000/1e6)*10 + (1000/1e6)*30 = 0.01 + 0.03 = 0.04
    assert cost_cheap == pytest.approx(0.0003, rel=1e-6)
    assert cost_pricey == pytest.approx(0.04, rel=1e-6)
    assert cost_pricey > cost_cheap


# ---------------------------------------------------------------------------
# Test 4: unknown model -> None (never borrows another model's price)
# ---------------------------------------------------------------------------
async def test_unknown_model_cost_is_none(monkeypatch):
    pricing = {
        "known-model": {"input_per_1m": 1.0, "output_per_1m": 2.0},
    }
    monkeypatch.setattr("app.observability.tracking._load_pricing", lambda: pricing)
    monkeypatch.setattr("app.observability.tracking.record_event", _noop_record_event)

    # A model that is not in the pricing map must yield None, not 0, not the
    # known-model price.
    assert tracking.compute_cost(model="mystery-model", input_tokens=1000, output_tokens=1000) is None
    # Empty/None model also yields None.
    assert tracking.compute_cost(model=None, input_tokens=1000, output_tokens=1000) is None

    # End-to-end: unknown model writes cost NULL even when tokens are present.
    engine = _make_engine()
    await _init_db(engine)
    SessionMaker = _fake_llm_session_factory(engine)
    async with SessionMaker() as session:
        await _seed_metric(session, "run-t4")
        tracking.set_run_context(session=session, run_id="run-t4")
        await tracking.record_llm_call(
            input_tokens=1000,
            output_tokens=1000,
            model="mystery-model",
            usage_available=True,  # usage IS available, but no pricing
        )
        repo = RunRepository(session)
        metric = await repo.get_metric("run-t4")
        assert metric.model == "mystery-model"
        assert metric.usage_available is True
        assert metric.input_tokens == 1000
        assert metric.estimated_cost_usd is None


# ---------------------------------------------------------------------------
# Test 5: streaming still emits tokens even when no usage is present
# ---------------------------------------------------------------------------
async def test_streaming_tokens_not_broken_without_usage():
    from app.agents import graph as graph_mod
    from langchain_core.messages import AIMessage

    # A normal streamed text chunk must still produce a token.
    chunk = AIMessage(content="streamed text")
    token = graph_mod._token_from_chunk(chunk)
    assert token == "streamed text"

    # And it must carry no usage_metadata (so streaming output is unaffected).
    assert graph_mod._usage_from_message(chunk) is None

    # A chunk that only has a tool call must NOT be emitted as a token.
    from langchain_core.messages import AIMessageChunk

    tool_chunk = AIMessageChunk(content="", tool_call_chunks=[{"name": "x", "args": "{}", "id": "c1", "index": 0}])
    assert graph_mod._token_from_chunk(tool_chunk) is None
