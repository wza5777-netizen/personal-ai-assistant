"""Pydantic schemas for API request/response validation."""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(default="", description="ID of the requesting user")
    message: str = Field(..., description="User message text")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Agent response text")
