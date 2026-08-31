"""Repository helpers for conversations and their messages.

Reuses the existing ORM models (Conversation / Message). No new tables are
created here — these functions only read/write the already-migrated schema.
"""
from datetime import datetime, timezone
from sqlalchemy import select, tuple_

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
            id=uuid.uuid4().hex, user_id=user_id, title="新对话"
        )
        session.add(conversation)
        await session.flush()
    return conversation


DEFAULT_CONVERSATION_TITLE = "新对话"
TITLE_MAX_LENGTH = 30


def derive_title(text: str) -> str:
    """Derive a lightweight conversation title from the first user message.

    Uses the first message as-is, truncated to ``TITLE_MAX_LENGTH`` chars. No
    LLM call is involved.
    """
    title = text.strip().replace("\n", " ")
    if len(title) > TITLE_MAX_LENGTH:
        title = title[:TITLE_MAX_LENGTH]
    return title or DEFAULT_CONVERSATION_TITLE


async def update_conversation_title(
    session, conversation_id: str, title: str
) -> None:
    """Set the conversation title (e.g. from the first user message)."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is not None:
        conversation.title = title
        conversation.updated_at = _now()
        await session.flush()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def list_conversations(current_user_id: str) -> list[Conversation]:
    """Return the user's conversations ordered by ``updated_at`` descending."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == current_user_id)
            .order_by(Conversation.updated_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


# --- Message paging -------------------------------------------------------
# A chat UI renders the newest messages and pulls older history on demand, so
# messages are paged backwards (newest-first) from the end of the conversation.
DEFAULT_MESSAGE_PAGE_SIZE = 20
MAX_MESSAGE_PAGE_SIZE = 100


async def get_messages(
    conversation_id: str,
    current_user_id: str,
    limit: int = DEFAULT_MESSAGE_PAGE_SIZE,
    before: str | None = None,
) -> tuple[list[Message], bool]:
    """Return one page of messages for ``conversation_id``, oldest to newest.

    Paging is newest-first and cursor based: ``before`` is the id of the oldest
    message the client already holds, and the returned page contains the
    messages strictly older than it. Omitting ``before`` yields the most recent
    ``limit`` messages. Within a page the messages are still ordered
    chronologically (ascending) so the UI can render them directly.

    Enforces a double check: the conversation must exist AND belong to
    ``current_user_id``. Any mismatch returns an empty page so another user's
    data is never exposed. ``current_user_id`` is always derived server-side
    (never trusted from the client).

    Returns ``(messages, has_more)``; ``has_more`` reports whether older
    messages are still available.
    """
    limit = max(1, min(limit, MAX_MESSAGE_PAGE_SIZE))
    async with AsyncSessionLocal() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != current_user_id:
            return [], False

        stmt = select(Message).where(Message.conversation_id == conversation_id)

        if before:
            anchor = await session.get(Message, before)
            # An unknown anchor (or one belonging to another conversation)
            # yields an empty page instead of silently restarting from the
            # newest messages, which would duplicate rows on the client.
            if anchor is None or anchor.conversation_id != conversation_id:
                return [], False
            if anchor.created_at is not None:
                # Row-wise comparison keeps paging stable when several
                # messages share a timestamp; ``id`` breaks the tie.
                stmt = stmt.where(
                    tuple_(Message.created_at, Message.id)
                    < tuple_(anchor.created_at, anchor.id)
                )
            else:
                stmt = stmt.where(Message.id < anchor.id)

        # Fetch one extra row purely to detect whether more history exists.
        stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(
            limit + 1
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        rows.reverse()
        return rows, has_more


async def get_recent_conversation(current_user_id: str) -> Conversation | None:
    """Return the user's most recent conversation, or ``None`` if they have none.

    ``current_user_id`` is always derived server-side.
    """
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == current_user_id)
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalars().first()
