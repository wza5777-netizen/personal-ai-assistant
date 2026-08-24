"""LangGraph agent state definition."""
from typing import Annotated, Optional

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """State passed between graph nodes.

    Attributes:
        messages: running list of conversation messages.
        user_id: the current user for tool execution scoping.
        response: final assistant response (filled by the LLM node).
        conversation_id: optional conversation id used for approval scoping.
        approval_id: set when the agent pauses for a HIGH-risk tool approval.
    """

    messages: Annotated[list[BaseMessage], Field(default_factory=list)]
    user_id: str = "default-user"
    response: str = ""
    conversation_id: str | None = None
    approval_id: str | None = None
    user_permissions: list[str] = Field(default_factory=list)
