"""Pydantic schemas for observability run views (Admin API)."""
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class RunStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    approval_required = "approval_required"
    cancelled = "cancelled"


class RunSummary(BaseModel):
    """Lightweight run entry for list views (no final answer / CoT)."""

    run_id: str
    user_id: str
    conversation_id: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    latency_ms: Optional[int] = None
    llm_calls: int = 0
    tool_calls: int = 0
    tool_failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class TraceEventView(BaseModel):
    """A single timeline step. ``details`` are fact-only (no LLM chain-of-thought)."""

    sequence: int
    event_type: str
    timestamp: datetime
    tool_name: Optional[str] = None
    status: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class ToolCallView(BaseModel):
    """Tool invocation summary extracted from trace events."""

    sequence: int
    tool_name: str
    status: Optional[str] = None
    arguments: Optional[dict[str, Any]] = None
    result_ok: Optional[bool] = None


class RunDetail(BaseModel):
    """Full run detail including timeline, tool calls, final status, latency, tokens."""

    run_id: str
    user_id: str
    conversation_id: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    latency_ms: Optional[int] = None
    prompt: Optional[str] = None
    final_response: Optional[str] = None
    error: Optional[str] = None

    llm_calls: int = 0
    tool_calls: int = 0
    tool_failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0

    timeline: list[TraceEventView] = []
    tool_calls_detail: list[ToolCallView] = []


class RunListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    runs: list[RunSummary]
