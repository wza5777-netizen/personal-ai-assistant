import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "个人 AI 助手",
  description: "企业级 AI Agent 项目基础架构",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">
        <header className="border-b border-white/10 px-6 py-4">
          <nav className="mx-auto flex max-w-5xl items-center justify-between">
            <span className="font-semibold">AI 助手</span>
            <div className="space-x-4 text-sm text-gray-300">
              <Link href="/" className="hover:text-white">
                首页
              </Link>
              <Link href="/chat" className="hover:text-white">
                对话
              </Link>
              <Link href="/tasks" className="hover:text-white">
                任务
              </Link>
              <Link href="/calendar" className="hover:text-white">
                日历
              </Link>
              <Link href="/memories" className="hover:text-white">
                记忆
              </Link>
              <Link href="/knowledge" className="hover:text-white">
                知识库
              </Link>
              <Link href="/approvals" className="hover:text-white">
                审批
              </Link>
              <Link href="/admin/runs" className="hover:text-white">
                运维观测
              </Link>
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
