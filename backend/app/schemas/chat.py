"""Pydantic schemas for API request/response validation."""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message text")
    conversation_id: str | None = Field(
        default=None, description="Existing conversation to append to (optional)"
    )


class MessageItem(BaseModel):
    id: str = Field(..., description="Message id; also used as a paging cursor")
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message text")
    created_at: str = Field(..., description="ISO creation timestamp")


class MessagePage(BaseModel):
    """One page of a conversation's messages (newest-first paging).

    ``items`` is chronological (oldest to newest) within the page. When
    ``has_more`` is true, pass ``items[0].id`` as the ``before`` cursor to
    fetch the preceding (older) page.
    """

    items: list[MessageItem] = Field(
        default_factory=list, description="Messages in this page, oldest first"
    )
    next_cursor: str | None = Field(
        default=None, description="Cursor (message id) for the next older page"
    )
    has_more: bool = Field(
        default=False, description="Whether older messages are still available"
    )


class ConversationItem(BaseModel):
    id: str = Field(..., description="Conversation id")
    title: str | None = Field(default=None, description="Conversation title")
    created_at: str = Field(..., description="ISO creation timestamp")
    updated_at: str = Field(..., description="ISO last-update timestamp")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Agent response text")
    conversation_id: str = Field(..., description="Conversation this exchange belongs to")
