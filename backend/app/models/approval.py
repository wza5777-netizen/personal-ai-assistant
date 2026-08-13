"""Approval request for high-risk tool execution (human-in-the-loop)."""
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class Approval(Base):
    """A pending human-approval request for a HIGH-risk tool call.

    When the agent requests a HIGH-risk tool, the gateway creates an
    ``Approval`` row with ``status='pending'``, returns the id to the caller,
    and the agent is paused until a human approves or rejects it.
    """

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
