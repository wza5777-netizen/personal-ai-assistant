"""Pydantic schemas for API request/response validation."""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(default="", description="ID of the requesting user")
    message: str = Field(..., description="User message text")
    conversation_id: str | None = Field(
        default=None, description="Existing conversation to append to (optional)"
    )


class MessageItem(BaseModel):
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message text")
    created_at: str = Field(..., description="ISO creation timestamp")


class ConversationItem(BaseModel):
    id: str = Field(..., description="Conversation id")
    title: str | None = Field(default=None, description="Conversation title")
    created_at: str = Field(..., description="ISO creation timestamp")
    updated_at: str = Field(..., description="ISO last-update timestamp")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Agent response text")
    conversation_id: str = Field(..., description="Conversation this exchange belongs to")
