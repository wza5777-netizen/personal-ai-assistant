"use client";

import { useCallback, useRef, useState } from "react";

import { apiClient, StreamEvent } from "./api-client";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/** A node in the Agent execution timeline (tool calls, status changes, results). */
export interface TimelineEntry {
  id: string;
  type: "tool_call" | "tool_result" | "agent_start" | "agent_end" | "error";
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

const USER_ID = "default-user";

/**
 * Chat controller with three explicitly separated concerns:
 * - ``messages``: the left-hand conversation (incl. live-streamed assistant text)
 * - ``agentTimeline``: the right-hand Agent execution timeline
 * - ``streamingStatus``: the current streaming lifecycle state
 * A ``token`` event updates only ``messages``; timeline events update only
 * ``agentTimeline``. They never share state.
 */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [agentTimeline, setAgentTimeline] = useState<TimelineEntry[]>([]);
  const [streamingStatus, setStreamingStatus] = useState<StreamingStatus>("idle");
  // Short status line ("正在搜索知识库…") shown next to the live reply.
  const [agentStatus, setAgentStatus] = useState("");

  // Maps tool_call_id -> timeline entry index so tool_result merges in place.
  const timelineIndexByCallId = useRef<Map<string, number>>(new Map());

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
          // Reset timeline for a fresh run; chat keeps prior messages.
          setAgentTimeline([]);
          timelineIndexByCallId.current.clear();
          addTimelineEntry({ type: "agent_start", timestamp: event.timestamp });
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
          addTimelineEntry({
            type: "tool_call",
            tool_name: event.tool_name ?? "unknown",
            arguments: event.arguments,
            risk_level: event.risk_level,
            tool_call_id: event.tool_call_id,
            timestamp: event.timestamp,
          });
          setAgentStatus(describeToolStatus(event.tool_name));
          break;
        case "tool_result":
          addTimelineEntry({
            type: "tool_result",
            tool_name: event.tool_name ?? "unknown",
            tool_call_id: event.tool_call_id,
            status: event.status,
            result: event.result,
            approval_id: event.approval_id,
            timestamp: event.timestamp,
          });
          break;
        case "agent_end":
          addTimelineEntry({
            type: "agent_end",
            status: event.status,
            approval_id: event.approval_id,
            timestamp: event.timestamp,
          });
          if (event.status === "awaiting_approval" && event.approval_id) {
            appendToken(
              `\n\n⏸️ 已暂停：正在等待您批准高风险工具调用（approval_id=${event.approval_id}）。请前往「审批」页面处理。`
            );
            setAgentStatus("等待审批…");
          } else {
            setAgentStatus("");
          }
          break;
        case "error":
          addTimelineEntry({
            type: "error",
            message: event.message ?? "未知错误",
            timestamp: event.timestamp,
          });
          setAgentStatus("出错了，请重试");
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
        { user_id: USER_ID, message: text },
        handleEvent
      );
      setStreamingStatus("done");
    } catch {
      // Network / connection failure: keep generated text, mark error.
      appendToken("\n\n生成失败，请重试。");
      addTimelineEntry({ type: "error", message: "连接或流式服务失败" });
      setStreamingStatus("error");
    }
  }, [input, streamingStatus, handleEvent, appendToken, addTimelineEntry]);

  return {
    messages,
    input,
    setInput,
    send,
    agentTimeline,
    streamingStatus,
    agentStatus,
  };
}
