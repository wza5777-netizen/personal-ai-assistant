"""Event Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventBase(BaseModel):
    title: str = Field(..., max_length=256)
    description: Optional[str] = None
    start_time: datetime
    end_time: datetime
    status: str = "scheduled"

    @model_validator(mode="after")
    def _check_time_order(self) -> "EventBase":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=256)
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    status: Optional[str] = None


class EventOut(EventBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    created_at: datetime
    updated_at: datetime
