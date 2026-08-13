"use client";

import { useEffect, useState } from "react";
import { apiClient, CalendarEvent } from "@/lib/api-client";

export default function CalendarPage() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiClient
      .listEvents()
      .then(setEvents)
      .catch((e) => setError(e.message ?? "加载日程失败"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">日历</h1>
      <p className="text-sm text-gray-400">
        在对话中让 Agent 帮你安排日程，例如：“帮我安排一个明天下午 3
        点的产品评审会议”。冲突的时间段会被自动拒绝。
      </p>

      {loading && <p className="text-sm text-gray-500">加载中…</p>}
      {error && <p className="text-sm text-red-400">错误：{error}</p>}
      {!loading && !error && events.length === 0 && (
        <p className="text-sm text-gray-500">暂无日程。</p>
      )}

      <ul className="space-y-3">
        {events.map((e) => (
          <li
            key={e.id}
            className="rounded-lg border border-white/10 p-4"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{e.title}</span>
              <span className="rounded bg-white/10 px-2 py-0.5 text-xs text-gray-300">
                {e.status}
              </span>
            </div>
            {e.description && (
              <p className="mt-1 text-sm text-gray-400">{e.description}</p>
            )}
            <div className="mt-2 text-xs text-gray-500">
              {new Date(e.start_time).toLocaleString()} →{" "}
              {new Date(e.end_time).toLocaleString()}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
