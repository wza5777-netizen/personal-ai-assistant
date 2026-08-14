"""Chat endpoints (non-streaming + SSE streaming)."""
import asyncio
import json
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.agents.graph import invoke_agent
from app.context.stream import set_run_id, set_stream_sink, to_sse
from app.database.session import AsyncSessionLocal
from app.models.approval import Approval
from app.models.conversation import Conversation
from app.models.message import Message
from app.observability import tracking
from app.repositories.conversation_repository import (
    get_or_create_conversation,
    get_messages,
    get_recent_conversation,
    list_conversations,
    update_conversation_title,
    derive_title,
    DEFAULT_CONVERSATION_TITLE,
)
from app.schemas.chat import ChatRequest, ChatResponse, MessageItem, ConversationItem

router = APIRouter()

DEFAULT_USER_ID = "default-user"


async def _ensure_user_and_conversation(session, user_id: str, conversation_id: str | None) -> Conversation:
    """Get-or-create a persistent user/conversation so context can be built later.

    If ``conversation_id`` is supplied and owned by ``user_id`` it is reused;
    otherwise the user's most recent conversation is reused or a new one created.
    """
    return await get_or_create_conversation(session, user_id, conversation_id)


async def _persist_message(
    session, conversation_id: str, role: str, content: str
) -> None:
    session.add(
        Message(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Accept a user message, run the agent, and persist the exchange.

    The acting user identity is always ``DEFAULT_USER_ID`` (server-side); the
    client-supplied ``request.user_id`` is intentionally ignored.
    """
    current_user_id = DEFAULT_USER_ID
    messages = [HumanMessage(content=request.message)]

    async with AsyncSessionLocal() as session:
        conversation = await _ensure_user_and_conversation(session, current_user_id, request.conversation_id)
        conv_id = conversation.id
        await _persist_message(session, conv_id, "user", request.message)
        # Lightweight auto-title: first user message becomes the title (only if
        # the conversation still has the default title). No LLM involved.
        if conversation.title == DEFAULT_CONVERSATION_TITLE:
            await update_conversation_title(session, conv_id, derive_title(request.message))
        await session.commit()

    result = await invoke_agent(messages, user_id=current_user_id, conversation_id=conv_id)

    async with AsyncSessionLocal() as session:
        await _persist_message(session, conv_id, "assistant", result["response"])
        await session.commit()

    return ChatResponse(response=result["response"], conversation_id=conv_id)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageItem])
async def get_conversation_messages(conversation_id: str) -> list[MessageItem]:
    """Return all messages of a conversation ordered by time ascending.

    The acting user is the server-side ``DEFAULT_USER_ID``; the conversation
    must belong to them. Other users' conversations return an empty list.
    """
    current_user_id = DEFAULT_USER_ID
    messages = await get_messages(conversation_id, current_user_id)
    return [
        MessageItem(
            role=m.role,
            content=m.content,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in messages
    ]


@router.get("/conversations", response_model=list[ConversationItem])
async def list_conversations_route() -> list[ConversationItem]:
    """Return the current user's conversations ordered by ``updated_at`` desc.

    Used by the frontend to recover the latest conversation when no
    ``conversation_id`` is stored locally, and as the basis for a future chat
    list sidebar.
    """
    current_user_id = DEFAULT_USER_ID
    conversations = await list_conversations(current_user_id)
    return [
        ConversationItem(
            id=c.id,
            title=c.title,
            created_at=c.created_at.isoformat() if c.created_at else "",
            updated_at=c.updated_at.isoformat() if c.updated_at else "",
        )
        for c in conversations
    ]


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream the agent run over SSE.

    Emits events ``agent_start``, ``tool_call``, ``tool_result``, ``token``,
    ``agent_end`` in real time. When the agent pauses for a HIGH-risk tool, an
    ``agent_end`` event with ``status='awaiting_approval'`` is emitted.
    """
    current_user_id = DEFAULT_USER_ID
    messages = [HumanMessage(content=request.message)]

    async def event_generator():
        # Ensure a conversation/row exists before the run so approvals can be
        # scoped correctly, then run the agent with a live stream sink.
        async with AsyncSessionLocal() as session:
            conversation = await _ensure_user_and_conversation(session, current_user_id, request.conversation_id)
            conv_id = conversation.id
            await _persist_message(session, conv_id, "user", request.message)
            if conversation.title == DEFAULT_CONVERSATION_TITLE:
                await update_conversation_title(session, conv_id, derive_title(request.message))
            await session.commit()

            queue: asyncio.Queue = asyncio.Queue()

            async def sink(payload: dict) -> None:
                await queue.put(to_sse(payload))

            set_stream_sink(sink)

            # Establish the observability run context for this request.
            run_id = uuid.uuid4().hex
            set_run_id(run_id)
            tracking.set_run_context(session=session, run_id=run_id)
            await tracking.start_run(
                user_id=current_user_id, conversation_id=conv_id, prompt=request.message
            )

            try:
                run_task = asyncio.create_task(
                    invoke_agent(
                        messages,
                        user_id=current_user_id,
                        conversation_id=conv_id,
                        db=session,
                    )
                )
                # Stream queued events until the run completes. Events are
                # yielded the moment they are produced (no server-side buffering
                # of the full answer).
                while True:
                    try:
                        frame = await asyncio.wait_for(queue.get(), timeout=0.1)
                        yield frame
                    except asyncio.TimeoutError:
                        if run_task.done():
                            # Drain any remaining frames then stop.
                            while not queue.empty():
                                yield await queue.get()
                            break
                try:
                    result = run_task.result()
                except Exception as exc:  # noqa: BLE001 - last-resort guard
                    result = {"response": "", "approval_id": None, "error": True}
                    await tracking.record_event("error", details={"message": str(exc)[:500]})
                    yield to_sse({"type": "error", "message": str(exc)})

                # Finalize the persisted run according to the outcome.
                if result.get("approval_id"):
                    await tracking.finish_run(
                        "approval_required",
                        final_response=result.get("response") or "",
                    )
                elif result.get("error"):
                    await tracking.finish_run(
                        "failed", final_response=result.get("response") or ""
                    )
                else:
                    await tracking.finish_run(
                        "completed", final_response=result.get("response") or ""
                    )
            except asyncio.CancelledError:
                # Client disconnected mid-stream: end the run as cancelled so the
                # Admin Runs view reflects a terminal state (no orphaned runs).
                await tracking.finish_run("cancelled")
                raise
            finally:
                set_stream_sink(None)
                tracking.clear_run_context()

        # Persist the assistant response / approval outcome.
        async with AsyncSessionLocal() as session:
            assistant_text = result.get("response") or ""
            if result.get("approval_id"):
                assistant_text = (
                    assistant_text
                    or f"[已暂停] 等待您批准高风险工具调用 (approval_id={result['approval_id']})"
                )
            await _persist_message(session, conv_id, "assistant", assistant_text)
            await session.commit()

        yield to_sse({"type": "done", "conversation_id": conv_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
