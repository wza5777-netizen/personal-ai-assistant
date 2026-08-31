"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  apiClient,
  MESSAGE_PAGE_SIZE,
  RunInfo,
  StreamEvent,
  TraceEventView,
} from "./api-client";
import { conversationKeyFor } from "./auth-storage";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/**
 * A node in the Agent execution timeline. The same shape is produced both by
 * the live SSE stream and by hydration from the persisted DB timeline, so the
 * UI never maintains two event models.
 */
export type TimelineEventType =
  | "agent_start"
  | "llm_start"
  | "llm_end"
  | "tool_call"
  | "tool_result"
  | "memory_retrieval"
  | "knowledge_retrieval"
  | "agent_end"
  | "error";

export interface TimelineEntry {
  id: string;
  type: TimelineEventType;
  tool_name?: string;
  arguments?: Record<string, unknown>;
  risk_level?: string;
  tool_call_id?: string;
  status?: string;
  result?: unknown;
  approval_id?: string;
  message?: string;
  timestamp?: number;
}

/**
 * Convert a persisted DB trace event into the unified TimelineEntry model.
 * This mirrors the SSE mapping in ``sseToTimelineEntry`` so both sources render
 * identically.
 */
export function traceToTimelineEntry(ev: TraceEventView): TimelineEntry {
  const details = (ev.details as Record<string, unknown>) ?? {};
  let toolName = ev.tool_name ?? (typeof details["tool"] === "string" ? (details["tool"] as string) : undefined);
  let riskLevel: string | undefined;
  let argumentsPayload: Record<string, unknown> | undefined;
  let result: unknown;
  let message: string | undefined;

  switch (ev.event_type) {
    case "memory_retrieval":
      toolName = "记忆检索";
      message = `查询「${details["query"] ?? ""}」命中 ${details["hits"] ?? 0} 条`;
      break;
    case "knowledge_retrieval":
      toolName = "知识库检索";
      message = `查询「${details["query"] ?? ""}」命中 ${details["hits"] ?? 0} 条`;
      break;
    case "tool_call":
      argumentsPayload = (details["arguments"] as Record<string, unknown>) ?? undefined;
      riskLevel = typeof details["risk_level"] === "string" ? (details["risk_level"] as string) : undefined;
      break;
    case "tool_result": {
      argumentsPayload = (details["arguments"] as Record<string, unknown>) ?? undefined;
      const output = details["output_summary"];
      result = output !== undefined ? output : argumentsPayload;
      break;
    }
    case "error":
      message = typeof details["message"] === "string" ? (details["message"] as string) : "执行出错";
      break;
    default:
      break;
  }

  return {
    id: `db-${ev.sequence}`,
    type: ev.event_type as TimelineEventType,
    tool_name: toolName,
    arguments: argumentsPayload,
    risk_level: riskLevel,
    status: ev.status ?? undefined,
    result,
    message,
    timestamp: ev.timestamp ? Date.parse(ev.timestamp) : undefined,
  };
}

/**
 * Convert a live SSE event into the unified TimelineEntry model. Extracted from
 * the previous inline handling so hydration and streaming share one shape.
 */
export function sseToTimelineEntry(event: StreamEvent): Omit<TimelineEntry, "id"> {
  switch (event.type) {
    case "agent_start":
      return { type: "agent_start", timestamp: event.timestamp };
    case "tool_call":
      return {
        type: "tool_call",
        tool_name: event.tool_name ?? "unknown",
        arguments: event.arguments,
        risk_level: event.risk_level,
        tool_call_id: event.tool_call_id,
        timestamp: event.timestamp,
      };
    case "tool_result":
      return {
        type: "tool_result",
        tool_name: event.tool_name ?? "unknown",
        tool_call_id: event.tool_call_id,
        status: event.status,
        result: event.result,
        approval_id: event.approval_id,
        timestamp: event.timestamp,
      };
    case "agent_end":
      return {
        type: "agent_end",
        status: event.status,
        approval_id: event.approval_id,
        timestamp: event.timestamp,
      };
    case "error":
      return { type: "error", message: event.message ?? "未知错误", timestamp: event.timestamp };
    default:
      return { type: "error" };
  }
}

export type StreamingStatus = "idle" | "streaming" | "done" | "error";

/** Human-readable status shown in the conversation while the agent works. */
const TOOL_STATUS_LABELS: Record<string, string> = {
  search_knowledge: "正在搜索知识库…",
  list_tasks: "正在查询任务…",
  create_task: "正在创建任务…",
  query_calendar: "正在查询日程…",
  create_event: "正在创建日程…",
  update_event: "正在更新日程…",
  current_time: "正在获取时间…",
  save_memory: "正在保存记忆…",
  search_memory: "正在检索记忆…",
};

function describeToolStatus(toolName?: string): string {
  if (!toolName) return "正在处理…";
  return TOOL_STATUS_LABELS[toolName] ?? `正在使用工具 ${toolName}…`;
}

const LEGACY_CONVERSATION_ID_KEY = "conversation_id";

/**
 * Resolve the conversation-storage key for the current user. The conversation
 * id is treated as per-user client state so that User B never restores User A's
 * chat after a logout/login. Falls back to the legacy shared key when no user
 * is known yet (e.g. guest) — but in practice the chat route is only rendered
 * for an authenticated user, so ``userId`` is always provided.
 */
function conversationKey(userId?: string | null): string {
  return userId ? conversationKeyFor(userId) : LEGACY_CONVERSATION_ID_KEY;
}

function readConversationId(userId?: string | null): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(conversationKey(userId));
}

function writeConversationId(userId: string | null | undefined, id: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(conversationKey(userId), id);
}

/**
 * Chat controller with three explicitly separated concerns:
 * - ``messages``: the left-hand conversation (incl. live-streamed assistant text)
 * - ``agentTimeline``: the right-hand Agent execution timeline
 * - ``streamingStatus``: the current streaming lifecycle state
 * A ``token`` event updates only ``messages``; timeline events update only
 * ``agentTimeline``. They never share state.
 *
 * @param userId  current authenticated user id (for user-scoped conversation
 *                persistence). Passed by the chat page from the auth context.
 */
export function useChat(userId?: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [agentTimeline, setAgentTimeline] = useState<TimelineEntry[]>([]);
  const [streamingStatus, setStreamingStatus] = useState<StreamingStatus>("idle");
  // Short status line ("正在搜索知识库…") shown next to the live reply.
  const [agentStatus, setAgentStatus] = useState("");
  // Persisted conversation id used across reloads (localStorage).
  const [conversationId, setConversationId] = useState<string | null>(null);
  // Lightweight run info for the most recent restored run (shown above timeline).
  const [runInfo, setRunInfo] = useState<RunInfo | null>(null);
  // True when the timeline (observability) failed to load. Chat must still work.
  const [timelineError, setTimelineError] = useState(false);
  // Conversation history is paged: only the newest page is held in memory and
  // older messages are fetched on demand ("load earlier messages").
  const [hasMoreMessages, setHasMoreMessages] = useState(false);
  const [loadingMoreMessages, setLoadingMoreMessages] = useState(false);
  // Id of the oldest message currently loaded — the cursor for the next older
  // page. Kept in a ref so paging never depends on a re-render.
  const oldestMessageIdRef = useRef<string | null>(null);

  // Maps tool_call_id -> timeline entry index so tool_result merges in place.
  const timelineIndexByCallId = useRef<Map<string, number>>(new Map());

  // Restore the persisted Agent Timeline for a conversation from the DB.
  // Failures here MUST NOT affect chat history loading (observability is a
  // secondary, best-effort feature).
  const loadTimeline = useCallback(async (convId: string) => {
    try {
      const list = await apiClient.getLatestRunForConversation(convId, 1);
      const latest = list.runs?.[0];
      if (!latest) {
        setRunInfo(null);
        setAgentTimeline([]);
        setTimelineError(false);
        return;
      }
      const detail = await apiClient.getRunTimeline(latest.run_id);
      // Hydrate timeline from persisted trace events (ordered by sequence).
      const entries = [...detail.timeline]
        .sort((a, b) => a.sequence - b.sequence)
        .map((ev) => traceToTimelineEntry(ev));
      setAgentTimeline(entries);
      setRunInfo({
        run_id: detail.run_id,
        status: detail.status,
        latency_ms: detail.latency_ms,
        model: detail.model,
        input_tokens: detail.input_tokens,
        output_tokens: detail.output_tokens,
        total_tokens: detail.total_tokens,
        estimated_cost_usd: detail.estimated_cost_usd,
        usage_available: detail.usage_available,
      });
      setTimelineError(false);
    } catch {
      // Observability is auxiliary: keep chat usable, surface a soft error state.
      setTimelineError(true);
      setRunInfo(null);
      setAgentTimeline([]);
    }
  }, []);

  // Load a conversation's messages + Agent Timeline into state. Used on mount to
  // restore history. The two loads run in parallel; a timeline failure is
  // isolated and never blocks the chat messages.
  const loadConversation = useCallback(
    async (convId: string) => {
      const id = (convId ?? "").trim();
      if (!id) return;
      setConversationId(id);
      writeConversationId(userId, id);
      setTimelineError(false);
      const [msgResult] = await Promise.allSettled([
        apiClient
          .getConversationMessages(id, { limit: MESSAGE_PAGE_SIZE })
          .then((page) => {
            const items = page.items ?? [];
            // Always replace: switching to an empty conversation must clear
            // the previous one's messages.
            setMessages(items.map((m) => ({ role: m.role, content: m.content })));
            oldestMessageIdRef.current = items.length > 0 ? items[0].id : null;
            setHasMoreMessages(Boolean(page.has_more));
          }),
        loadTimeline(id),
      ]);
      if (msgResult.status === "rejected") {
        // Ignore load failures; the conversation simply starts empty.
        setMessages([]);
        oldestMessageIdRef.current = null;
        setHasMoreMessages(false);
      }
    },
    [loadTimeline]
  );

  // Fetch the next (older) page of messages and prepend it. Newly sent
  // messages do not affect the cursor because it always tracks the oldest
  // loaded message, not the newest.
  const loadMoreMessages = useCallback(async (): Promise<boolean> => {
    const cursor = oldestMessageIdRef.current;
    if (!conversationId || !cursor || !hasMoreMessages || loadingMoreMessages) {
      return false;
    }
    setLoadingMoreMessages(true);
    try {
      const page = await apiClient.getConversationMessages(conversationId, {
        limit: MESSAGE_PAGE_SIZE,
        before: cursor,
      });
      const items = page.items ?? [];
      if (items.length > 0) {
        oldestMessageIdRef.current = items[0].id;
        setMessages((prev) => [
          ...items.map((m) => ({ role: m.role, content: m.content })),
          ...prev,
        ]);
      }
      setHasMoreMessages(Boolean(page.has_more));
      return items.length > 0;
    } catch {
      // Keep the already loaded messages; the user can retry.
      return false;
    } finally {
      setLoadingMoreMessages(false);
    }
  }, [conversationId, hasMoreMessages, loadingMoreMessages]);

  // On mount: restore chat history so it survives a page refresh.
  // Prefer a locally stored conversation id; if absent (or invalid), fall back
  // to the user's most recent conversation from the backend.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const savedId = readConversationId(userId);
    if (savedId) {
      loadConversation(savedId);
      return;
    }
    apiClient
      .getConversations()
      .then((convs) => {
        if (convs.length > 0) {
          loadConversation(convs[0].id);
        }
      })
      .catch(() => {
        // No conversations yet; start fresh.
      });
  }, [loadConversation]);

  // Append a streamed token to the last assistant message, creating one only
  // if the previous last message is not an assistant turn. The target index is
  // derived purely from the `prev` snapshot inside the updater — never from a
  // ref — so concurrent tokens batched in the same React tick all land in the
  // same message instead of spawning duplicate bubbles.
  const appendToken = useCallback((token: string) => {
    setMessages((prev) => {
      const next = prev.slice();
      const lastIdx = next.length - 1;
      if (lastIdx >= 0 && next[lastIdx].role === "assistant") {
        next[lastIdx] = { ...next[lastIdx], content: next[lastIdx].content + token };
      } else {
        next.push({ role: "assistant", content: token });
      }
      return next;
    });
  }, []);

  const addTimelineEntry = useCallback((entry: Omit<TimelineEntry, "id">) => {
    const id = `${entry.type}-${entry.tool_call_id ?? Math.random()}`;
    setAgentTimeline((prev) => {
      if (
        (entry.type === "tool_result" || entry.type === "agent_end") &&
        entry.tool_call_id
      ) {
        const idx = timelineIndexByCallId.current.get(entry.tool_call_id);
        if (idx !== undefined && prev[idx]) {
          const updated = [...prev];
          updated[idx] = {
            ...updated[idx],
            status: entry.status ?? updated[idx].status,
            result: entry.result ?? updated[idx].result,
            approval_id: entry.approval_id ?? updated[idx].approval_id,
            message: entry.message ?? updated[idx].message,
          };
          return updated;
        }
      }
      const newEntry: TimelineEntry = { id, ...entry };
      if (entry.type === "tool_call" && entry.tool_call_id) {
        timelineIndexByCallId.current.set(entry.tool_call_id, prev.length);
      }
      return [...prev, newEntry];
    });
  }, []);

  const handleEvent = useCallback(
    (event: StreamEvent) => {
      switch (event.type) {
        case "agent_start":
          // Reset timeline for a fresh run; chat keeps prior messages. Also drop
          // any hydrated run-info block from a previous (restored) run.
          setAgentTimeline([]);
          setRunInfo(null);
          setTimelineError(false);
          timelineIndexByCallId.current.clear();
          addTimelineEntry(sseToTimelineEntry(event));
          setAgentStatus("正在思考…");
          break;
        case "token":
          // Only the left-hand chat is updated by tokens.
          if (event.content) {
            appendToken(event.content);
            setAgentStatus("正在生成回答…");
          }
          break;
        case "tool_call":
          addTimelineEntry(sseToTimelineEntry(event));
          setAgentStatus(describeToolStatus(event.tool_name));
          break;
        case "tool_result":
          addTimelineEntry(sseToTimelineEntry(event));
          break;
        case "agent_end": {
          addTimelineEntry(sseToTimelineEntry(event));
          if (event.status === "awaiting_approval" && event.approval_id) {
            appendToken(
              `\n\n⏸️ 已暂停：正在等待您批准高风险工具调用（approval_id=${event.approval_id}）。请前往「审批」页面处理。`
            );
            setAgentStatus("等待审批…");
          } else {
            setAgentStatus("");
          }
          break;
        }
        case "error":
          addTimelineEntry(sseToTimelineEntry(event));
          setAgentStatus("出错了，请重试");
          break;
        case "done":
          // Persist the conversation id returned by the backend so history can
          // be restored after a page refresh.
          if (event.conversation_id) {
            writeConversationId(userId, event.conversation_id);
            setConversationId(event.conversation_id);
          }
          break;
        default:
          break;
      }
    },
    [appendToken, addTimelineEntry]
  );

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streamingStatus === "streaming") return;

    // 1) Immediately show the user message. No empty assistant bubble —
    //    the assistant reply appears only when the first token arrives.
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    timelineIndexByCallId.current.clear();
    setInput("");
    setStreamingStatus("streaming");
    setAgentStatus("正在思考…");

    try {
      await apiClient.streamChat(
        { message: text, conversation_id: conversationId },
        handleEvent
      );
      setStreamingStatus("done");
    } catch {
      // Network / connection failure: keep generated text, mark error.
      appendToken("\n\n生成失败，请重试。");
      addTimelineEntry({ type: "error", message: "连接或流式服务失败" });
      setStreamingStatus("error");
    }
  }, [input, streamingStatus, conversationId, handleEvent, appendToken, addTimelineEntry]);

  return {
    messages,
    input,
    setInput,
    send,
    agentTimeline,
    streamingStatus,
    agentStatus,
    runInfo,
    timelineError,
    hasMoreMessages,
    loadingMoreMessages,
    loadMoreMessages,
  };
}
