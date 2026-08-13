"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiClient, RunDetail, TraceEventView } from "@/lib/api-client";

const EVENT_ICON: Record<string, string> = {
  agent_start: "▶",
  llm_start: "🧠",
  llm_end: "🧠",
  tool_call: "🔧",
  tool_result: "✅",
  memory_retrieval: "🧩",
  knowledge_retrieval: "📚",
  approval_requested: "⏳",
  agent_end: "⏹",
  error: "⚠",
};

function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-white/10 p-3">
      <div className="text-xs text-gray-400">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function Timeline({ events }: { events: TraceEventView[] }) {
  return (
    <ol className="relative space-y-2 border-l border-white/10 pl-4">
      {events.map((ev) => (
        <li key={ev.sequence} className="relative">
          <span className="absolute -left-[21px] top-1 text-sm">
            {EVENT_ICON[ev.event_type] ?? "•"}
          </span>
          <div className="rounded border border-white/10 p-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-blue-300">{ev.event_type}</span>
              {ev.tool_name && (
                <span className="text-xs text-gray-400">tool: {ev.tool_name}</span>
              )}
              <span className="text-xs text-gray-500">
                {new Date(ev.timestamp).toLocaleTimeString()}
              </span>
            </div>
            {ev.details && (
              <pre className="mt-1 max-h-40 overflow-auto rounded bg-black/30 p-2 text-xs text-gray-300">
                {JSON.stringify(ev.details, null, 2)}
              </pre>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function RunDetailPage({
  params,
}: {
  params: { runId: string };
}) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiClient.getRun(params.runId);
        if (active) setRun(data);
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : "加载失败");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [params.runId]);

  return (
    <div className="space-y-6">
      <Link href="/admin/runs" className="text-sm text-blue-400 hover:underline">
        ← 返回列表
      </Link>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {loading && <p className="text-sm text-gray-400">加载中…</p>}

      {run && (
        <>
          <div className="flex items-center justify-between">
            <h1 className="font-mono text-lg">Run {run.run_id.slice(0, 8)}</h1>
            <span className="rounded bg-white/10 px-2 py-1 text-xs">{run.status}</span>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label="状态" value={run.status} />
            <Metric label="时长" value={formatDuration(run.latency_ms)} />
            <Metric label="工具调用" value={`${run.tool_calls} (失败 ${run.tool_failures})`} />
            <Metric label="LLM 调用" value={run.llm_calls} />
            <Metric label="输入 Token" value={run.input_tokens} />
            <Metric label="输出 Token" value={run.output_tokens} />
            <Metric label="总 Token" value={run.total_tokens} />
            <Metric label="预估成本" value={`$${run.estimated_cost_usd.toFixed(5)}`} />
          </div>

          {run.error && (
            <div className="rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
              {run.error}
            </div>
          )}

          <section>
            <h2 className="mb-2 font-semibold">用户输入</h2>
            <p className="rounded border border-white/10 p-3 text-sm text-gray-300">
              {run.prompt ?? "—"}
            </p>
          </section>

          {run.final_response && (
            <section>
              <h2 className="mb-2 font-semibold">最终回复</h2>
              <p className="whitespace-pre-wrap rounded border border-white/10 p-3 text-sm text-gray-300">
                {run.final_response}
              </p>
            </section>
          )}

          <section>
            <h2 className="mb-2 font-semibold">工具调用</h2>
            <div className="overflow-x-auto rounded border border-white/10">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-white/10 text-gray-400">
                  <tr>
                    <th className="px-3 py-2">#</th>
                    <th className="px-3 py-2">工具</th>
                    <th className="px-3 py-2">状态</th>
                    <th className="px-3 py-2">参数</th>
                    <th className="px-3 py-2">结果</th>
                  </tr>
                </thead>
                <tbody>
                  {run.tool_calls_detail.map((tc) => (
                    <tr key={tc.sequence} className="border-b border-white/5">
                      <td className="px-3 py-2">{tc.sequence}</td>
                      <td className="px-3 py-2 font-mono text-xs">{tc.tool_name}</td>
                      <td className="px-3 py-2">{tc.status ?? "—"}</td>
                      <td className="px-3 py-2">
                        <pre className="max-w-xs overflow-auto text-xs text-gray-400">
                          {tc.arguments ? JSON.stringify(tc.arguments, null, 2) : "—"}
                        </pre>
                      </td>
                      <td className="px-3 py-2">
                        {tc.result_ok == null
                          ? "—"
                          : tc.result_ok
                          ? "✅"
                          : "❌"}
                      </td>
                    </tr>
                  ))}
                  {run.tool_calls_detail.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-3 py-4 text-center text-gray-500">
                        本次运行未调用工具
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h2 className="mb-2 font-semibold">执行时间线</h2>
            <Timeline events={run.timeline} />
          </section>
        </>
      )}
    </div>
  );
}
