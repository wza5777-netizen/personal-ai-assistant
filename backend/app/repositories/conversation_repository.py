"""Repository helpers for conversations and their messages.

Reuses the existing ORM models (Conversation / Message). No new tables are
created here — these functions only read/write the already-migrated schema.
"""
from sqlalchemy import select

from app.database.session import AsyncSessionLocal
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User


async def get_or_create_conversation(
    session, user_id: str, conversation_id: str | None = None
) -> Conversation:
    """Return the conversation identified by ``conversation_id`` if it belongs to
    ``user_id``; otherwise get-or-create the user's most recent conversation.

    Security: when ``conversation_id`` is supplied we verify the conversation is
    owned by ``user_id`` before returning it. A mismatch resolves to a fresh
    conversation rather than leaking another user's data.
    """
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=f"{user_id}@local", display_name=user_id)
        session.add(user)
        await session.flush()

    if conversation_id:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is not None and conversation.user_id == user_id:
            return conversation

    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    conversation = result.scalars().first()
    if conversation is None:
        import uuid

        conversation = Conversation(
            id=uuid.uuid4().hex, user_id=user_id, title="默认会话"
        )
        session.add(conversation)
        await session.flush()
    return conversation


async def get_messages(conversation_id: str, user_id: str) -> list[Message]:
    """Return all messages for ``conversation_id`` ordered by time ascending.

    Only returns messages if the conversation is owned by ``user_id``; otherwise
    an empty list is returned to avoid exposing other users' data.
    """
    async with AsyncSessionLocal() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            return []
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_recent_conversation(user_id: str) -> Conversation | None:
    """Return the user's most recent conversation, or ``None`` if they have none."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalars().first()
