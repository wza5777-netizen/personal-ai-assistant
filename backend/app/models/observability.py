"""Observability models: agent runs, trace events, and aggregated run metrics."""
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class AgentRun(Base):
    """A single agent execution (one user message -> one complete response)."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)

    # Overall run status: running | completed | failed | approval_required | cancelled
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Total latency in milliseconds (finished_at - started_at).
    latency_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Final answer text (omitted from list endpoints via schema, included in detail).
    final_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error detail, if the run failed.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # User prompt (kept for trace context; no secrets are ever stored here).
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    def finish(self, status: str, *, final_response: str | None = None, error: str | None = None) -> None:
        self.status = status
        self.finished_at = datetime.now(timezone.utc)
        if final_response is not None:
            self.final_response = final_response
        if error is not None:
            self.error = error
        if self.started_at is not None:
            self.latency_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)


class TraceEvent(Base):
    """A single structured event emitted during an agent run (a timeline step)."""

    __tablename__ = "trace_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )

    # Event kind: agent_start | llm_start | llm_end | tool_call | tool_result |
    #   memory_retrieval | knowledge_retrieval | approval_requested | agent_end | error
    event_type: Mapped[str] = mapped_column(String(48), index=True)

    # Monotonic sequence number within a run (for ordered timeline rendering).
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Free-form JSON payload (tool name, args summary, token counts, etc.).
    # The ``content``/``details`` string intentionally NEVER contains raw LLM
    # chain-of-thought reasoning, only observable facts.
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Convenience denormalised columns for fast filtering / display.
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)


class RunMetric(Base):
    """Aggregated, queryable metrics for an agent run (LLM/tool/token/cost)."""

    __tablename__ = "run_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True, unique=True
    )

    # Counts.
    llm_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Token usage.
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Estimated USD cost for the run.
    # NULL means "unavailable" (provider didn't return usage, or the model has
    # no configured pricing). This is deliberately distinct from 0.0.
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, default=None, nullable=True)

    # The actual model that served the LLM calls for this run (e.g. gpt-4o-mini).
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Whether the provider returned real token usage for this run.
    # False => token counts are absent (NOT the same as 0 tokens).
    usage_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
