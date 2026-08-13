"use client";

import { useCallback, useEffect, useState } from "react";

import { apiClient, ApprovalDecision, ApprovalItem } from "@/lib/api-client";

function statusBadge(status: ApprovalItem["status"]) {
  const map: Record<ApprovalItem["status"], string> = {
    pending: "bg-amber-500/20 text-amber-300",
    approved: "bg-green-500/20 text-green-300",
    rejected: "bg-red-500/20 text-red-300",
  };
  const label: Record<ApprovalItem["status"], string> = {
    pending: "待审批",
    approved: "已批准",
    rejected: "已拒绝",
  };
  return (
    <span className={`rounded px-2 py-0.5 text-xs ${map[status]}`}>
      {label[status]}
    </span>
  );
}

export default function ApprovalsPage() {
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await apiClient.listApprovals(false));
    } catch {
      setError("无法加载审批列表。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const decide = useCallback(
    async (id: string, decision: ApprovalDecision) => {
      setBusyId(id);
      try {
        await apiClient.decideApproval(id, decision);
        await load();
      } catch {
        setError("操作失败，请重试。");
      } finally {
        setBusyId(null);
      }
    },
    [load]
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">高风险工具审批</h1>
        <button
          onClick={load}
          disabled={loading}
          className="rounded-lg border border-white/10 px-3 py-1.5 text-sm hover:bg-white/5 disabled:opacity-50"
        >
          刷新
        </button>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="space-y-3">
        {items.length === 0 && !loading && (
          <p className="text-sm text-gray-500">暂无审批请求。</p>
        )}
        {items.map((item) => (
          <div
            key={item.id}
            className="rounded-lg border border-white/10 p-4 text-sm"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-semibold">{item.tool_name}</span>
                {statusBadge(item.status)}
              </div>
              <span className="text-xs text-gray-500">
                {new Date(item.created_at).toLocaleString("zh-CN")}
              </span>
            </div>

            <div className="mt-2 text-xs text-gray-400">
              <span className="text-gray-500">approval_id:</span> {item.id}
            </div>

            <pre className="mt-2 max-h-48 overflow-auto rounded bg-white/5 p-2 text-xs text-gray-300">
              {typeof item.arguments === "string"
                ? item.arguments
                : JSON.stringify(item.arguments, null, 2)}
            </pre>

            {item.decision_reason && (
              <p className="mt-2 text-xs text-gray-400">
                备注：{item.decision_reason}
              </p>
            )}

            {item.status === "pending" && (
              <div className="mt-3 flex gap-2">
                <button
                  onClick={() => decide(item.id, { status: "approved" })}
                  disabled={busyId === item.id}
                  className="rounded-lg bg-green-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                >
                  批准
                </button>
                <button
                  onClick={() => decide(item.id, { status: "rejected" })}
                  disabled={busyId === item.id}
                  className="rounded-lg bg-red-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                >
                  拒绝
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
