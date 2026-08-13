"use client";

import { useChat } from "@/lib/use-chat";

function riskBadge(risk?: string) {
  if (risk === "high") {
    return (
      <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] font-medium text-red-300">
        HIGH
      </span>
    );
  }
  if (risk === "medium") {
    return (
      <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
        MED
      </span>
    );
  }
  return null;
}

function statusBadge(status?: string) {
  const map: Record<string, string> = {
    success: "bg-green-500/20 text-green-300",
    awaiting_approval: "bg-red-500/20 text-red-300",
    completed: "bg-blue-500/20 text-blue-300",
    pending: "bg-amber-500/20 text-amber-300",
  };
  if (!status || !(status in map)) return null;
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] ${map[status]}`}>
      {status}
    </span>
  );
}

export default function ChatPage() {
  const {
    messages,
    input,
    setInput,
    send,
    agentTimeline,
    streamingStatus,
    agentStatus,
  } = useChat();
  const streaming = streamingStatus === "streaming";
  // True while the last message is the assistant reply being generated.
  const generating =
    streaming && messages.length > 0 && messages[messages.length - 1].role === "assistant";

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">对话</h1>

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        {/* Conversation column */}
        <div className="space-y-3">
          {streamingStatus === "error" && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              生成失败，请重试。
            </div>
          )}

          <div className="space-y-3 rounded-lg border border-white/10 p-4">
            {messages.length === 0 && (
              <p className="text-sm text-gray-500">暂无消息，来打个招呼吧！</p>
            )}
            {messages.map((m, i) => (
              <div
                key={i}
                className={`flex flex-col gap-1 ${m.role === "user" ? "items-end" : "items-start"}`}
              >
                {generating &&
                  m.role === "assistant" &&
                  i === messages.length - 1 &&
                  agentStatus && (
                    <div className="flex items-center gap-2 rounded-md bg-white/5 px-2.5 py-1.5 text-xs text-gray-400">
                      <span className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-gray-500 border-t-transparent" />
                      {agentStatus}
                    </div>
                  )}
                <div
                  className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm ${
                    m.role === "user"
                      ? "bg-blue-600 text-white"
                      : "bg-white/10 text-gray-100"
                  }`}
                >
                  {m.content}
                  {streaming &&
                    m.role === "assistant" &&
                    i === messages.length - 1 && (
                      <span className="ml-1 inline-block animate-pulse">▌</span>
                    )}
                </div>
              </div>
            ))}
            {streaming && agentStatus && !generating && (
              <div className="flex items-center gap-2 rounded-md bg-white/5 px-2.5 py-1.5 text-xs text-gray-400">
                <span className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-gray-500 border-t-transparent" />
                {agentStatus}
              </div>
            )}
            {streaming && messages.length === 0 && (
              <p className="text-sm text-gray-500">思考中…</p>
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
            className="flex gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入消息…"
              className="flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
            <button
              type="submit"
              disabled={streaming || !input.trim()}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              发送
            </button>
          </form>
        </div>

        {/* Agent execution timeline */}
        <aside className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-300">
            Agent 执行 Timeline
          </h2>
          <div className="max-h-[70vh] space-y-2 overflow-y-auto rounded-lg border border-white/10 p-3">
            {agentTimeline.length === 0 && (
              <p className="text-xs text-gray-500">
                运行 Agent 后，这里会实时展示工具调用、状态变化与执行结果。
              </p>
            )}
            {agentTimeline.map((entry) => (
              <div
                key={entry.id}
                className="rounded-md border border-white/5 bg-white/5 p-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-gray-200">
                    {entry.tool_name ?? entry.type}
                  </span>
                  <div className="flex items-center gap-1">
                    {riskBadge(entry.risk_level)}
                    {statusBadge(entry.status)}
                    {entry.type === "error" && (
                      <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] text-red-300">
                        error
                      </span>
                    )}
                  </div>
                </div>
                {entry.message && (
                  <p className="mt-1 text-[10px] text-red-300">{entry.message}</p>
                )}
                {entry.arguments && (
                  <pre className="mt-1 overflow-x-auto text-[10px] text-gray-400">
                    {JSON.stringify(entry.arguments, null, 2)}
                  </pre>
                )}
                {entry.result !== undefined && (
                  <pre className="mt-1 overflow-x-auto text-[10px] text-gray-400">
                    {typeof entry.result === "string"
                      ? entry.result
                      : JSON.stringify(entry.result, null, 2)}
                  </pre>
                )}
                {entry.approval_id && (
                  <p className="mt-1 text-[10px] text-red-300">
                    需审批：{entry.approval_id}
                  </p>
                )}
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
