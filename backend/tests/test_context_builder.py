"""Tests for the Context Builder prompt rendering (no DB required)."""
from app.context import Context


def test_context_prompt_with_memories_and_summary():
    ctx = Context(
        memories=[
            {"type": "preference", "content": "喜欢喝美式咖啡", "importance": 5}
        ],
        conversation_summary=[
            {"role": "user", "content": "帮我安排明天会议"},
            {"role": "assistant", "content": "好的"},
        ],
    )
    prompt = ctx.to_system_prompt()
    assert "喜欢喝美式咖啡" in prompt
    assert "importance 5" in prompt
    assert "帮我安排明天会议" in prompt
    assert "assistant: 好的" in prompt


def test_context_prompt_empty():
    ctx = Context()
    assert ctx.to_system_prompt() == ""


def test_context_prompt_memories_only():
    ctx = Context(memories=[{"type": "fact", "content": "家住北京", "importance": 8}])
    prompt = ctx.to_system_prompt()
    assert "家住北京" in prompt
    assert "最近的对话记录" not in prompt
