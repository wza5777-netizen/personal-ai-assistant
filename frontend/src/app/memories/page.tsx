"use client";

import { useEffect, useState } from "react";
import { apiClient, Memory } from "@/lib/api-client";

const TYPE_COLORS: Record<string, string> = {
  fact: "bg-blue-500/20 text-blue-300",
  preference: "bg-purple-500/20 text-purple-300",
  user_info: "bg-green-500/20 text-green-300",
  goal: "bg-amber-500/20 text-amber-300",
  general: "bg-white/10 text-gray-300",
};

export default function MemoriesPage() {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .listMemories()
      .then(setMemories)
      .catch((e) => setError(e.message ?? "加载记忆失败"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">记忆</h1>
      <p className="text-sm text-gray-400">
        在对话中让 Agent 记住你的信息，例如：“记住我喜欢喝美式咖啡”。Agent
        会在每次回答前检索这些记忆作为上下文。
      </p>

      {loading && <p className="text-sm text-gray-500">加载中…</p>}
      {error && <p className="text-sm text-red-400">错误：{error}</p>}
      {!loading && !error && memories.length === 0 && (
        <p className="text-sm text-gray-500">暂无记忆。</p>
      )}

      <ul className="space-y-3">
        {memories.map((m) => (
          <li
            key={m.id}
            className="rounded-lg border border-white/10 p-4"
          >
            <div className="flex items-center justify-between">
              <span
                className={`rounded px-2 py-0.5 text-xs ${
                  TYPE_COLORS[m.type] ?? TYPE_COLORS.general
                }`}
              >
                {m.type}
              </span>
              <span className="text-xs text-gray-500">
                重要度 {m.importance}/10
              </span>
            </div>
            <p className="mt-2 text-sm text-gray-200">{m.content}</p>
            <div className="mt-2 text-xs text-gray-500">
              {new Date(m.updated_at).toLocaleString()}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
