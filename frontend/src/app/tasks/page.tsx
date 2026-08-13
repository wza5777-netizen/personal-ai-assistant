"use client";

import { useEffect, useState } from "react";
import { apiClient, Task } from "@/lib/api-client";

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .listTasks()
      .then(setTasks)
      .catch((e) => setError(e.message ?? "加载任务失败"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">任务</h1>
      <p className="text-sm text-gray-400">
        在对话中让 Agent 帮你创建任务，例如：“帮我创建一个任务：明天提交周报”。
      </p>

      {loading && <p className="text-sm text-gray-500">加载中…</p>}
      {error && <p className="text-sm text-red-400">错误：{error}</p>}
      {!loading && !error && tasks.length === 0 && (
        <p className="text-sm text-gray-500">暂无任务。</p>
      )}

      <ul className="space-y-3">
        {tasks.map((t) => (
          <li
            key={t.id}
            className="rounded-lg border border-white/10 p-4"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{t.title}</span>
              <span className="rounded bg-white/10 px-2 py-0.5 text-xs text-gray-300">
                {t.status}
              </span>
            </div>
            {t.description && (
              <p className="mt-1 text-sm text-gray-400">{t.description}</p>
            )}
            <div className="mt-2 text-xs text-gray-500">
              优先级：{t.priority}
              {t.due_time && ` · 截止：${new Date(t.due_time).toLocaleString()}`}
              {` · 创建：${new Date(t.created_at).toLocaleString()}`}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
