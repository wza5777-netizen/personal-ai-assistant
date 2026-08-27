"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useChat } from "@/lib/use-chat";
import { useSpeechInput } from "@/lib/use-speech-input";
import { useAuth } from "@/lib/auth-context";

/**
 * 把语音识别文本拼接到输入框已有内容之后：
 * - 空原内容：直接使用识别文本；
 * - 原内容以 ASCII 字母/数字结尾（如 "hello"）：补一个空格，避免粘连；
 * - 中文等结尾（如 "帮我"）：直接拼接，不加空格。
 */
function joinSpeech(base: string, speech: string): string {
  if (!speech) return base;
  if (!base) return speech;
  const lastChar = base[base.length - 1];
  const needsSpace = /[A-Za-z0-9]/.test(lastChar);
  return needsSpace ? `${base} ${speech}` : `${base}${speech}`;
}

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

function runInfoBlock(runInfo: import("@/lib/api-client").RunInfo | null) {
  if (!runInfo) return null;
  const costLabel =
    runInfo.estimated_cost_usd != null
      ? `$${runInfo.estimated_cost_usd.toFixed(4)}`
      : runInfo.usage_available
        ? "Cost unavailable"
        : "Token usage unavailable";
  const tokenLabel = runInfo.usage_available
    ? `${runInfo.input_tokens}↑ / ${runInfo.output_tokens}↓`
    : "Token usage unavailable";
  return (
    <div className="mb-3 rounded-lg border border-white/10 bg-white/5 p-2 text-[11px] text-gray-300">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium text-gray-200">最近运行</span>
        {statusBadge(runInfo.status)}
        {runInfo.model && (
          <span className="rounded bg-sky-500/20 px-1.5 py-0.5 text-[10px] text-sky-300">
            {runInfo.model}
          </span>
        )}
        {runInfo.latency_ms != null && <span>⏱ {runInfo.latency_ms}ms</span>}
        <span title="input / output tokens">🔢 {tokenLabel}</span>
        <span title="estimated cost">💲 {costLabel}</span>
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { isLoading, isAuthenticated, logout } = useAuth();
  const router = useRouter();

  // Route protection: while restoring auth state, show a neutral loading state;
  // if not authenticated, send the user to /login BEFORE rendering any chat UI
  // (so we never briefly show (and never hit the API as) a guest).
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace("/login");
    }
  }, [isLoading, isAuthenticated, router]);

  if (isLoading) {
    return (
      <p className="py-20 text-center text-sm text-gray-400">正在验证身份…</p>
    );
  }
  if (!isAuthenticated) {
    return null;
  }

  return <ChatView onLogout={logout} />;
}

function ChatView({ onLogout }: { onLogout: () => void }) {
  const { user } = useAuth();
  const {
    messages,
    input,
    setInput,
    send,
    agentTimeline,
    streamingStatus,
    agentStatus,
    runInfo,
    timelineError,
  } = useChat(user?.id);
  const streaming = streamingStatus === "streaming";
  const {
    isSupported: isSpeechSupported,
    isListening,
    transcript: speechTranscript,
    error: speechError,
    startListening,
    stopListening,
  } = useSpeechInput();
  // 开始录音前保存输入框原内容，识别结果只做「追加」，绝不覆盖已输入文字。
  const speechBaseRef = useRef("");

  function handleMicToggle() {
    if (isListening) {
      stopListening();
    } else {
      speechBaseRef.current = input;
      startListening();
    }
  }

  // 识别过程中的 interim 结果实时写入 textarea；结束时写入最终结果。
  // 识别结束后只更新输入框，绝不自动发送 / 调用 Agent。
  useEffect(() => {
    if (isListening || speechTranscript) {
      setInput(joinSpeech(speechBaseRef.current, speechTranscript));
    }
  }, [speechTranscript, isListening, setInput]);

  function handleComposerKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter 发送；Shift+Enter 换行；中文输入法组词回车不触发发送。
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  }

  const scrollRef = useRef<HTMLDivElement>(null);
  // Auto-scroll to the newest message whenever the message list changes.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);
  // True while the last message is the assistant reply being generated.
  const generating =
    streaming && messages.length > 0 && messages[messages.length - 1].role === "assistant";

  function handleLogout() {
    onLogout();
    if (typeof window !== "undefined") {
      window.location.assign("/login");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">对话</h1>
        <button
          onClick={handleLogout}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-sm text-gray-300 hover:text-white"
        >
          退出登录
        </button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        {/* Conversation column */}
        <div className="space-y-3">
          {streamingStatus === "error" && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              生成失败，请重试。
            </div>
          )}

          <div
            ref={scrollRef}
            className="max-h-[70vh] space-y-3 overflow-y-auto rounded-lg border border-white/10 p-4"
          >
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
            className="flex items-end gap-2 pb-[max(env(safe-area-inset-bottom),0px)]"
          >
            <div className="min-w-0 flex-1">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleComposerKeyDown}
                placeholder={isListening ? "正在聆听…" : "输入消息…"}
                rows={1}
                enterKeyHint="send"
                className="max-h-40 min-h-11 w-full resize-none rounded-lg border border-white/10 bg-white/5 px-3 py-2.5 text-sm outline-none focus:border-blue-500"
              />
              {isListening && (
                <p className="mt-1 flex items-center gap-1.5 text-xs text-red-300">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-400" />
                  ● 正在聆听… 点击麦克风停止
                </p>
              )}
              {!isListening && speechError && (
                <p className="mt-1 text-xs text-amber-300" role="alert">
                  {speechError.message}
                </p>
              )}
            </div>

            <button
              type="button"
              onClick={handleMicToggle}
              disabled={!isSpeechSupported || streaming}
              title={
                !isSpeechSupported
                  ? "当前浏览器暂不支持语音输入"
                  : isListening
                    ? "停止录音"
                    : "语音输入"
              }
              aria-label={isListening ? "停止录音" : "开始语音输入"}
              aria-pressed={isListening}
              className={`flex h-11 w-11 shrink-0 touch-manipulation items-center justify-center rounded-lg border text-lg transition-colors ${
                isListening
                  ? "animate-pulse border-red-500/50 bg-red-500/20 text-red-300"
                  : "border-white/10 bg-white/5 text-gray-300 hover:text-white"
              } disabled:opacity-40`}
            >
              {isListening ? "⏹" : "🎤"}
            </button>

            <button
              type="submit"
              disabled={streaming || !input.trim()}
              className="h-11 shrink-0 touch-manipulation rounded-lg bg-blue-600 px-4 text-sm font-medium text-white disabled:opacity-50"
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
          {runInfoBlock(runInfo)}
          <div className="max-h-[70vh] space-y-2 overflow-y-auto rounded-lg border border-white/10 p-3">
            {timelineError && (
              <p className="text-xs text-amber-300/80">
                执行记录暂不可用（Trace 服务异常），聊天不受影响。
              </p>
            )}
            {!timelineError && agentTimeline.length === 0 && (
              <p className="text-xs text-gray-500">
                运行 Agent 后，这里会实时展示工具调用、状态变化与执行结果；刷新页面也会自动恢复上一次运行的记录。
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
