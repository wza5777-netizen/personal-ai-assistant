"""Tests for streaming events and the HIGH-risk human-approval gate.

These tests mock the LLM so they run without a real OpenAI API key. They
verify: (1) the agent emits the expected stream event types and (2) a HIGH-risk
tool creates an Approval row and pauses the agent via ApprovalRequired.
"""
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agents.graph import _token_from_chunk, invoke_agent
from app.context.stream import emit, set_stream_sink, to_sse
from app.models.approval import Approval
from app.tools import registry
from app.tools.base import RiskLevel
from app.tools.gateway import ApprovalRequired


def _tool_call_chunk(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


async def _collect_events(run_coro):
    """Run a coroutine with a live stream sink that collects emitted events."""
    events: list[dict] = []

    async def sink(payload: dict) -> None:
        events.append(payload)

    set_stream_sink(sink)
    try:
        result = await run_coro
    finally:
        set_stream_sink(None)
    return result, events


def test_token_from_chunk_filters_tool_call_turn():
    """Only final-answer text is streamed; tool-call turns are excluded."""
    # Final answer: plain text chunk -> streamed.
    assert _token_from_chunk(AIMessageChunk(content="你好")) == "你好"
    # Tool-call turn: empty content, has tool_call_chunks -> not streamed.
    tc_chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "current_time", "args": "{}", "id": "c1"}],
    )
    assert _token_from_chunk(tc_chunk) is None
    # A non-string content (e.g. multimodal list) is never streamed.
    assert _token_from_chunk(AIMessageChunk(content=[{"type": "text", "text": "x"}])) is None


@pytest.mark.asyncio
async def test_tool_loop_emits_timeline_events(monkeypatch):
    """Agent run emits agent_start, tool_call, tool_result, agent_end and a
    final answer — verifying the Agent→Tool→Gateway→Result→Agent flow."""
    fake_llm = MagicMock()

    async def fake_astream(messages):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            yield AIMessage(content="时间是 " + last.content)
        else:
            yield _tool_call_chunk("current_time", {}, "call_t")

    fake_llm.astream = fake_astream
    monkeypatch.setattr("app.agents.graph._build_llm", lambda: fake_llm)

    result, events = await _collect_events(
        invoke_agent([HumanMessage(content="现在几点")], user_id="u-test")
    )

    types = [e["type"] for e in events]
    assert "agent_start" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert "agent_end" in types
    assert result["response"].startswith("时间是 ")
    assert result["approval_id"] is None


@pytest.mark.asyncio
async def test_high_risk_tool_creates_approval_and_pauses(monkeypatch):
    """A HIGH-risk tool request creates an Approval and pauses the agent."""

    # Register a fake HIGH-risk tool.
    class HighRiskTool:
        name = "danger_tool"
        description = "high risk"
        risk_level = RiskLevel.HIGH
        parameters = {}

        async def execute(self, arguments, user_id=""):
            return "should not run"

    registry.register(HighRiskTool())

    fake_llm = MagicMock()

    async def fake_astream(messages):
        # Single call that requests the HIGH-risk tool; we expect a pause.
        yield _tool_call_chunk("danger_tool", {"x": 1}, "call_h")

    fake_llm.astream = fake_astream
    monkeypatch.setattr("app.agents.graph._build_llm", lambda: fake_llm)
    # Stub build_context to avoid touching the module-level DB engine under
    # pytest-asyncio's per-test event loop (unrelated to the approval flow).
    async def _fake_build_context(user_id, query):
        from app.context import Context

        return Context()

    monkeypatch.setattr("app.agents.graph.build_context", _fake_build_context)

    # Provide a DB session so the gateway can persist the approval.
    # Build a loop-scoped engine to avoid the asyncpg "different loop" quirk
    # that arises from the module-level engine under pytest-asyncio.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import get_settings
    from app.repositories.approval_repository import ApprovalRepository

    settings = get_settings()
    url = settings.database_url or "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_assistant"
    engine = create_async_engine(url)
    SessionMaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with SessionMaker() as session:
            result, events = await _collect_events(
                invoke_agent(
                    [HumanMessage(content="do the dangerous thing")],
                    user_id="u-test",
                    db=session,
                )
            )
            # Agent paused: no final answer, but an approval_id was set.
            assert result["approval_id"] is not None
            assert result["response"] == ""

            # An approval row exists with status 'pending'.
            repo = ApprovalRepository(session)
            approvals = await repo.list_all(user_id="u-test")
            pending = [a for a in approvals if a.tool_name == "danger_tool"]
            assert pending, "expected an approval record for the HIGH-risk tool"
            assert pending[0].status == "pending"

            # The stream emitted a tool_result with awaiting_approval status.
            awaiting = [
                e
                for e in events
                if e["type"] == "tool_result"
                and e.get("status") == "awaiting_approval"
            ]
            assert awaiting, "expected awaiting_approval stream event"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_approval_required_sentinel_carries_approval():
    with pytest.raises(ApprovalRequired) as exc_info:
        raise ApprovalRequired(Approval(id="a1", user_id="u", tool_name="t", arguments="{}"))
    assert exc_info.value.approval.id == "a1"


def test_to_sse_roundtrip():
    frame = to_sse({"type": "token", "content": "hi"})
    assert frame.startswith("data: ")
    assert frame.strip().endswith("}")
