import Link from "next/link";

export default function HomePage() {
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">个人 AI 助手</h1>
      <p className="text-gray-300">
        企业级 AI Agent 项目基础架构，基于 Next.js 15、FastAPI、LangGraph 和
        PostgreSQL 搭建。
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-white/10 p-4">
          <h2 className="font-semibold">对话</h2>
          <p className="mt-1 text-sm text-gray-400">与基于 LangGraph 的 Agent 交流。</p>
          <Link
            href="/chat"
            className="mt-3 inline-block text-sm text-blue-400 hover:underline"
          >
            进入对话 →
          </Link>
        </div>
        <div className="rounded-lg border border-white/10 p-4">
          <h2 className="font-semibold">任务</h2>
          <p className="mt-1 text-sm text-gray-400">
            让 Agent 帮你创建并查看任务清单。
          </p>
          <Link
            href="/tasks"
            className="mt-3 inline-block text-sm text-blue-400 hover:underline"
          >
            查看任务 →
          </Link>
        </div>
        <div className="rounded-lg border border-white/10 p-4">
          <h2 className="font-semibold">日历</h2>
          <p className="mt-1 text-sm text-gray-400">
            让 Agent 帮你安排会议与日程，自动检测时间冲突。
          </p>
          <Link
            href="/calendar"
            className="mt-3 inline-block text-sm text-blue-400 hover:underline"
          >
            查看日历 →
          </Link>
        </div>
        <div className="rounded-lg border border-white/10 p-4">
          <h2 className="font-semibold">接口</h2>
          <p className="mt-1 text-sm text-gray-400">
            FastAPI 文档位于 <code>/docs</code>。
          </p>
        </div>
        <div className="rounded-lg border border-white/10 p-4">
          <h2 className="font-semibold">运维观测</h2>
          <p className="mt-1 text-sm text-gray-400">
            查看 Agent 运行记录、执行时间线与工具调用明细。
          </p>
          <Link
            href="/admin/runs"
            className="mt-3 inline-block text-sm text-blue-400 hover:underline"
          >
            查看 Run 列表 →
          </Link>
        </div>
      </div>
    </div>
  );
}
