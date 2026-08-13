"""Approval Pydantic schemas (human-in-the-loop)."""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    tool_name: str
    arguments: Any
    status: str
    conversation_id: Optional[str] = None
    decision_reason: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None


class ApprovalDecision(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected)$")
    decision_reason: Optional[str] = None
