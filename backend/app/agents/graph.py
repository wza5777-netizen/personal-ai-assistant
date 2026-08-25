"""LangGraph agent with Tool Gateway support and streaming event output.

Flow (ReAct-style loop via the custom ToolGateway):

    START -> agent (LLM, streams tokens)
    agent -- has tool_calls --> tools (ToolGateway) -> agent
    agent -- no tool_calls  --> END
    tools -- approval required (HIGH risk) --> END (paused)

Business tools (current_time, create_task, ...) are wired in through the
registry; the agent binds whatever tools are registered.

While the graph runs it emits structured stream events (``agent_start``,
``tool_call``, ``tool_result``, ``token``, ``agent_end``) through the context
var sink set up by the SSE endpoint, enabling real-time UX (live tokens and an
execution timeline). ``LangGraph`` checkpointer is preserved for resumability.
"""
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    ToolMessage,
    AIMessage,
    SystemMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.state import AgentState
from app.config import settings
from app.context import build_context
from app.context.stream import emit
from app.observability import logger
from app.observability import tracking
from app.tools import gateway as tool_gateway
from app.tools.gateway import ApprovalRequired, set_db_session
from app.tools import calendar_tool  # noqa: F401  (registers calendar tools)
from app.tools import memory_tool  # noqa: F401  (registers memory tools)
from app.tools import task_tool  # noqa: F401  (registers create_task)
from app.tools.base import RiskLevel
from app.tools.registry import registry
from app.mcp.registry import mcp_registry

checkpointer = MemorySaver()
USER_ID = "default-user"


def _token_from_chunk(chunk) -> str | None:
    """Return the user-visible text to stream from an LLM chunk, or ``None``.

    Returns the chunk's text content only when it is a non-empty string AND the
    chunk carries no tool-call chunks. This guarantees that the internal
    tool-calling LLM turn (which has empty content and/or ``tool_call_chunks``)
    never leaks into the user-facing chat — only the final answer is streamed.
    """
    content = getattr(chunk, "content", "")
    tool_calls = getattr(chunk, "tool_call_chunks", None)
    if isinstance(content, str) and content and not tool_calls:
        return content
    return None


def _usage_from_message(message) -> tuple[int, int] | None:
    """Extract (input_tokens, output_tokens) from a LangChain message.

    ``usage_metadata`` is the canonical LangChain field; in streaming it is
    usually only attached to the final chunk / the ``on_chat_model_end`` output.
    It may be a dict or a pydantic-style object depending on the LangChain
    version. Returns ``None`` when the provider did not report any usage.
    """
    if message is None:
        return None
    usage = getattr(message, "usage_metadata", None)
    if not usage:
        return None
    # Support both dict and attribute-style access.
    if isinstance(usage, dict):
        in_t = usage.get("input_tokens")
        out_t = usage.get("output_tokens")
    else:
        in_t = getattr(usage, "input_tokens", None)
        out_t = getattr(usage, "output_tokens", None)
    if in_t is None and out_t is None:
        return None
    return (int(in_t or 0), int(out_t or 0))


def _model_from_chunk(chunk) -> str | None:
    """Best-effort model name from a streamed chunk's response metadata."""
    if chunk is None:
        return None
    meta = getattr(chunk, "response_metadata", None) or {}
    return (meta.get("model") or meta.get("model_name")) if isinstance(meta, dict) else None


def _model_from_message(message) -> str | None:
    """Best-effort model name from a completed message's response metadata."""
    if message is None:
        return None
    meta = getattr(message, "response_metadata", None) or {}
    if isinstance(meta, dict):
        return meta.get("model") or meta.get("model_name")
    return None


def _build_llm() -> ChatOpenAI:
    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
        temperature=0.7,
        # Disable thinking mode on Volcano Ark (Doubao-Seed) models.
        extra_body={"thinking": {"type": "disabled"}},
        # Reliability: bound each request and retry transient failures.
        timeout=60,
        max_retries=3,
    )
    schemas = registry.tool_schemas()
    # Include tools served by MCP servers (e.g. github.*) so the LLM knows they
    # exist and can choose to call them. They are routed back through the same
    # Tool Gateway, so RBAC/observability apply uniformly.
    mcp_schemas = mcp_registry.tool_schemas()
    if mcp_schemas:
        schemas = schemas + mcp_schemas
    if schemas:
        llm = llm.bind_tools(schemas)
    return llm


async def _agent_node(state: AgentState) -> dict:
    """Call the LLM (with tools bound) and append the accumulated message.

    Token-level streaming for the main chat is handled by the caller via
    LangGraph ``astream_events`` (``on_chat_model_stream``), so this node only
    accumulates the final AIMessage into the graph state. This keeps the
    tool-calling LLM turn (empty content) from leaking into the user chat.
    """
    await tracking.record_event("llm_start", details={"node": "agent"})
    llm = _build_llm()
    collected: list[BaseMessage] = []
    async for chunk in llm.astream(state.messages):
        if not collected:
            collected.append(chunk)
        else:
            collected[0] = collected[0] + chunk
    final = collected[0] if collected else AIMessage(content="")
    # Capture token usage from the accumulated message, if reported by the provider.
    usage = getattr(final, "usage_metadata", None)
    if usage is not None:
        inp = int(getattr(usage, "input_tokens", 0) or 0)
        out = int(getattr(usage, "output_tokens", 0) or 0)
        await tracking.record_llm_call(input_tokens=inp, output_tokens=out, model=settings.openai_model)
    else:
        await tracking.record_llm_call(model=settings.openai_model)
    return {"messages": state.messages + [final]}


def _should_continue(state: AgentState) -> str:
    """Route to the tools node if the last AI message requested a tool call."""
    if state.approval_id:
        return END  # paused for human approval
    last = state.messages[-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"
    return END


async def _tools_node(state: AgentState) -> dict:
    """Execute each requested tool through the ToolGateway and collect results.

    Emits ``tool_call`` / ``tool_result`` events and pauses the agent when a
    HIGH-risk tool requires human approval (captured in ``approval_id``).
    """
    last: AIMessage = state.messages[-1]
    tool_messages: list[ToolMessage] = []
    approval_id: str | None = None

    for call in last.tool_calls:
        name = call["name"]
        args = call.get("args", {}) or {}
        tool = registry.get_tool(name)
        risk = tool.risk_level.value if tool else "low"
        await emit(
            "tool_call",
            {
                "tool_name": name,
                "arguments": args,
                "risk_level": risk,
                "tool_call_id": call["id"],
            },
        )
        await tracking.record_tool_call(name, arguments=args)
        try:
            result = await tool_gateway.execute_tool(
                name,
                args,
                user_id=state.user_id,
                conversation_id=state.conversation_id,
                user_permissions=state.user_permissions,
            )
        except ApprovalRequired as exc:
            approval_id = exc.approval.id
            await emit(
                "tool_result",
                {
                    "tool_name": name,
                    "tool_call_id": call["id"],
                    "status": "awaiting_approval",
                    "approval_id": exc.approval.id,
                    "result": {
                        "status": "awaiting_approval",
                        "approval_id": exc.approval.id,
                    },
                },
            )
            await tracking.record_tool_result(name, ok=True, status="awaiting_approval")
            await tracking.record_approval_requested(name, exc.approval.id)
            # Stop tool processing; pause the agent for human approval.
            return {"approval_id": approval_id}
        tool_messages.append(ToolMessage(content=result, tool_call_id=call["id"]))
        ok = not result.startswith("Error")
        await tracking.record_tool_result(name, ok=ok, status="success" if ok else "error")
        await emit(
            "tool_result",
            {
                "tool_name": name,
                "tool_call_id": call["id"],
                "status": "success" if ok else "error",
                "result": result,
            },
        )

    return {"messages": state.messages + tool_messages}


def build_agent() -> StateGraph:
    """Construct the LangGraph state machine with the tool-calling loop."""
    graph = StateGraph(AgentState)
    graph.add_node("agent", _agent_node)
    graph.add_node("tools", _tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", _should_continue, {"tools": "tools", END: END}
    )
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)


# Compiled graph instance (singleton).
agent_app = build_agent()


async def invoke_agent(
    messages: list[HumanMessage],
    user_id: str = USER_ID,
    conversation_id: str | None = None,
    db=None,
    user_permissions: list[str] | None = None,
) -> dict:
    """Run the agent with the given messages and stream events as they happen.

    Uses LangGraph's ``astream_events`` so LLM token chunks are emitted to the
    stream sink in real time (never buffered into a full response first).

    Returns ``{"response", "approval_id", "error"}``. ``approval_id`` is set
    when the agent paused awaiting human approval of a HIGH-risk tool.
    ``error`` is ``True`` if the run failed (the partial response is still
    returned so the client can keep what was generated).

    Before execution, the Context Builder assembles relevant memories and a
    recent conversation summary which are injected as a system prompt.
    """
    if db is not None:
        set_db_session(db)
    await emit("agent_start", {"user_id": user_id})

    # Extract the latest user query for context retrieval.
    query = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) and msg.content:
            query = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    context = await build_context(user_id, query)
    context_prompt = context.to_system_prompt()

    base_system_prompt = (
        "你是用户的个人 AI 助手。用户上传的文档、简历、资料都属于用户自己的数据，"
        "你有权限在用户询问相关内容时通过 search_knowledge 工具进行检索并回答，"
        "不要以隐私、权限等理由拒绝。"
        "当用户询问待办任务、未完成任务或任务状态时，必须先调用 list_tasks 工具查询，"
        "不要直接回答没有任务。"
    )
    # When GitHub MCP is enabled, tell the agent the user's default GitHub
    # account so it can resolve "my <repo>" references without asking for owner.
    if settings.github_mcp_enabled and settings.github_default_owner:
        base_system_prompt += (
            f"\n用户默认的 GitHub 账号（owner）是 `{settings.github_default_owner}`。"
            "当用户说\"我的 <仓库名>\"或\"我的 GitHub 仓库\"而未指明 owner 时，"
            f"默认使用 `{settings.github_default_owner}` 作为仓库 owner，"
            "直接调用相应的 github.* 工具查询，不要向用户追问 owner。"
        )
    parts = [base_system_prompt]
    if context_prompt:
        parts.append(context_prompt)
    system_prompt = "\n\n".join(parts)

    initial_messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    initial_messages.extend(messages)

    # Derive the permission set for this run. When an MCP server is enabled we
    # grant its read-only permission so the agent may call that server's tools
    # (all of which are tagged with the matching required_permission). Explicit
    # permissions passed in are preserved and take precedence. We never grant a
    # write permission here — read-only is the only auto-grant.
    effective_permissions = list(user_permissions or [])
    if settings.github_mcp_enabled and "github:read" not in effective_permissions:
        effective_permissions.append("github:read")
    if settings.postgres_mcp_enabled and "database:read" not in effective_permissions:
        effective_permissions.append("database:read")

    initial_state: AgentState = AgentState(
        messages=initial_messages,
        user_id=user_id,
        response="",
        conversation_id=conversation_id,
        user_permissions=effective_permissions,
    )
    config = {"configurable": {"thread_id": f"default-{user_id}"}}

    def _final_text(values: dict) -> str:
        for msg in reversed(values.get("messages", [])):
            if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if content:
                    return content
        return ""

    try:
        # Real token usage is captured here (not estimated, not a second call).
        # In streaming mode, ``usage_metadata`` is typically only attached to the
        # FINAL model output chunk / the ``on_chat_model_end`` event. We therefore
        # accumulate it from the stream rather than relying on a single message.
        input_tokens = 0
        output_tokens = 0
        usage_seen = False
        # The actual model serving this run, taken from the live LLM config
        # (never hard-coded). Provider may also report it in response_metadata.
        model_name = settings.openai_model or None

        # Drive the graph with native event streaming: each LLM text chunk is
        # forwarded as a ``token`` event immediately. Tool-calling turns have
        # empty content and/or tool_call_chunks, so they are excluded here and
        # only surfaced via the Tool Gateway's tool_call/tool_result events.
        async for stream_event in agent_app.astream_events(
            initial_state, config=config, version="v2"
        ):
            event_type = stream_event.get("event")
            if event_type == "on_chat_model_stream":
                chunk = stream_event["data"]["chunk"]
                # Capture model name if the provider surfaces it on a chunk.
                if model_name is None:
                    model_name = _model_from_chunk(chunk) or model_name
                token = _token_from_chunk(chunk)
                if token:
                    await emit("token", {"content": token})
            elif event_type == "on_chat_model_end":
                # usage_metadata reliably lives on the end event's output. The
                # agent may do several LLM turns (tool-calling loop), so we
                # accumulate usage across all of them.
                output = stream_event.get("data", {}).get("output")
                captured = _usage_from_message(output)
                if captured is not None:
                    turn_in, turn_out = captured
                    input_tokens += turn_in
                    output_tokens += turn_out
                    usage_seen = True
                # Some providers also put the model in response_metadata.
                meta_model = _model_from_message(output)
                if meta_model:
                    model_name = meta_model

        snapshot = await agent_app.aget_state(config)
        values = snapshot.values or {}
        approval_id = values.get("approval_id")
        text = _final_text(values)

        # Persist real token usage + model-aware cost for observability.
        # If usage_metadata was never returned, explicitly mark it unavailable
        # (distinct from a genuine 0-token count) instead of faking data.
        if usage_seen:
            await tracking.record_llm_call(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=model_name,
                usage_available=True,
            )
        else:
            await tracking.record_llm_call(
                input_tokens=0,
                output_tokens=0,
                model=model_name,
                usage_available=False,
            )

        if approval_id:
            await emit(
                "agent_end",
                {"status": "awaiting_approval", "approval_id": approval_id},
            )
        else:
            await emit("agent_end", {"status": "completed", "response": text})
        return {"response": text, "approval_id": approval_id, "error": False}
    except Exception as exc:  # noqa: BLE001 - surface a stream error event
        logger.error("agent_run_failed", error=str(exc))
        await emit("error", {"message": str(exc)})
        # Best-effort: keep whatever partial answer the checkpointer captured.
        text = ""
        try:
            snapshot = await agent_app.aget_state(config)
            text = _final_text(snapshot.values or {})
        except Exception:  # noqa: BLE001
            pass
        return {"response": text, "approval_id": None, "error": True}
