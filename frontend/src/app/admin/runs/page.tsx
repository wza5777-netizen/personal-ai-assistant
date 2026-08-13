"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiClient, RunSummary } from "@/lib/api-client";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-green-500/20 text-green-300",
  failed: "bg-red-500/20 text-red-300",
  running: "bg-blue-500/20 text-blue-300",
  approval_required: "bg-yellow-500/20 text-yellow-300",
  cancelled: "bg-gray-500/20 text-gray-300",
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? "bg-gray-500/20 text-gray-300";
  return (
    <span className={`rounded px-2 py-0.5 text-xs font-medium ${cls}`}>{status}</span>
  );
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.listRuns(50, 0, statusFilter || undefined);
      setRuns(res.runs);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Agent 运行记录</h1>
        <div className="flex items-center gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded border border-white/10 bg-transparent px-2 py-1 text-sm"
          >
            <option value="">全部状态</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
            <option value="approval_required">approval_required</option>
            <option value="cancelled">cancelled</option>
            <option value="running">running</option>
          </select>
          <button
            onClick={load}
            className="rounded bg-blue-600 px-3 py-1 text-sm hover:bg-blue-500"
          >
            刷新
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {loading && <p className="text-sm text-gray-400">加载中…</p>}
      {!loading && !error && (
        <p className="text-sm text-gray-400">共 {total} 条运行记录</p>
      )}

      <div className="overflow-x-auto rounded-lg border border-white/10">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-white/10 text-gray-400">
            <tr>
              <th className="px-3 py-2">状态</th>
              <th className="px-3 py-2">Run ID</th>
              <th className="px-3 py-2">用户</th>
              <th className="px-3 py-2">时长</th>
              <th className="px-3 py-2">工具调用</th>
              <th className="px-3 py-2">Token</th>
              <th className="px-3 py-2">开始时间</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id} className="border-b border-white/5 hover:bg-white/5">
                <td className="px-3 py-2">
                  <StatusBadge status={r.status} />
                </td>
                <td className="px-3 py-2 font-mono text-xs">{r.run_id.slice(0, 8)}</td>
                <td className="px-3 py-2">{r.user_id}</td>
                <td className="px-3 py-2">{formatDuration(r.latency_ms)}</td>
                <td className="px-3 py-2">
                  {r.tool_calls}
                  {r.tool_failures > 0 && (
                    <span className="ml-1 text-red-400">({r.tool_failures}失败)</span>
                  )}
                </td>
                <td className="px-3 py-2">{r.total_tokens}</td>
                <td className="px-3 py-2 text-gray-400">
                  {new Date(r.started_at).toLocaleString()}
                </td>
                <td className="px-3 py-2">
                  <Link
                    href={`/admin/runs/${r.run_id}`}
                    className="text-blue-400 hover:underline"
                  >
                    详情 →
                  </Link>
                </td>
              </tr>
            ))}
            {!loading && runs.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-gray-500">
                  暂无运行记录
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
