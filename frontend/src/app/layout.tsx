import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";

export const metadata: Metadata = {
  title: "个人 AI 助手",
  description: "企业级 AI Agent 项目基础架构",
};

// 移动端视口配置：
// - viewportFit: cover 让 safe-area-inset-* 生效（iPhone 底部 Home 指示条）；
// - interactiveWidget: resizes-content 让 iOS 虚拟键盘弹起时压缩视口，
//   而不是遮挡 Composer。
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen antialiased">
        <AuthProvider>
          <header className="border-b border-white/10 px-4 py-3 sm:px-6 sm:py-4">
            <nav className="mx-auto flex max-w-5xl items-center gap-3">
              <span className="shrink-0 font-semibold">AI 助手</span>
              {/* 窄屏（375/390/430px）下横向滚动，避免导航溢出换行挤压内容 */}
              <div className="flex min-w-0 flex-1 items-center gap-x-3 gap-y-1 overflow-x-auto whitespace-nowrap text-sm text-gray-300 sm:justify-end sm:gap-x-4">
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
          <main className="mx-auto max-w-5xl px-4 py-6 pb-[max(env(safe-area-inset-bottom),1.5rem)] sm:px-6 sm:py-8">
            {children}
          </main>
        </AuthProvider>
      </body>
    </html>
  );
}
