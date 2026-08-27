"""Task Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TaskBase(BaseModel):
    title: str = Field(..., max_length=256)
    description: Optional[str] = None
    status: str = "pending"
    priority: str = "normal"
    due_time: Optional[datetime] = None


class TaskCreate(BaseModel):
    title: str = Field(..., max_length=256)
    description: Optional[str] = None
    due_time: Optional[datetime] = None


class TaskUpdate(BaseModel):
    """Partial update; only fields explicitly provided are applied."""

    title: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    due_time: Optional[datetime] = None
    status: Optional[str] = None


class TaskOut(TaskBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
