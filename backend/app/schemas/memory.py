"""Pydantic schemas for Memory."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MemoryCreate(BaseModel):
    type: str = Field(default="general", max_length=32, description="Memory type, e.g. fact/preference")
    content: str = Field(..., min_length=1, description="Memory content")
    importance: int = Field(default=1, ge=1, le=10, description="Importance 1-10")


class MemoryOut(MemoryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    created_at: datetime
    updated_at: datetime
