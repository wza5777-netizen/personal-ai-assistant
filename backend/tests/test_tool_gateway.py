"""Tests for the Agent Tool Gateway (Step 2).

These tests mock the LLM so they run without a real OpenAI API key and
verify the full Agent -> ToolGateway -> Tool closed loop.
"""
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.graph import agent_app, build_agent
from app.tools import gateway as tool_gateway
from app.tools.current_time import CurrentTimeTool
from app.tools.registry import registry


def test_registry_register_and_get():
    reg = registry
    tool = CurrentTimeTool()
    reg.register(tool)
    assert reg.get_tool("current_time") is tool
    assert tool in reg.list_tools()


@pytest.mark.asyncio
async def test_gateway_executes_current_time():
    result = await tool_gateway.execute_tool("current_time", {}, user_id="u1")
    # The result should contain a date-time pattern.
    assert len(result) > 0
    assert any(ch.isdigit() for ch in result)


@pytest.mark.asyncio
async def test_gateway_unknown_tool_returns_error():
    result = await tool_gateway.execute_tool("does_not_exist", {}, user_id="u1")
    assert "unknown tool" in result


def test_list_tools_includes_current_time():
    names = {t.name for t in registry.list_tools()}
    assert "current_time" in names


@pytest.mark.asyncio
async def test_question_triggers_current_time_tool(monkeypatch):
    """Input '现在几点' must trigger the current_time tool through the graph."""
    # Build a fresh graph with a mocked LLM that streams a tool call, then an
    # answer using the tool result (mirrors the production astream path).
    from app.agents.graph import _build_llm

    fake_llm = MagicMock()

    async def fake_astream(messages):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            yield AIMessage(content="现在的时间是 " + last.content)
        else:
            yield AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "current_time",
                        "args": {},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            )

    fake_llm.astream = fake_astream
    monkeypatch.setattr("app.agents.graph._build_llm", lambda: fake_llm)

    graph = build_agent()
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="现在几点")], "response": ""},
        config={"configurable": {"thread_id": "test-1"}},
    )

    # The graph must have executed the tool and produced a final answer.
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert tool_msgs, "current_time tool was not invoked"
    assert tool_msgs[0].tool_call_id == "call_1"
    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert "现在的时间" in final.content
    assert tool_msgs[0].content in final.content
