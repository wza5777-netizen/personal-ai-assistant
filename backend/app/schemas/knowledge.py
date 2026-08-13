"""Pydantic schemas for Knowledge."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    filename: str
    content_type: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime
