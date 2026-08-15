"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { authApi } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

export default function LoginPage() {
  const router = useRouter();
  const { setAuth, isAuthenticated } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // If already logged in, skip the form.
  if (isAuthenticated) {
    if (typeof window !== "undefined") window.location.assign("/chat");
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("请输入邮箱和密码");
      return;
    }
    setSubmitting(true);
    try {
      const res = await authApi.login(email, password);
      setAuth(res.access_token, res.user);
      router.replace("/chat");
    } catch (err) {
      // Show only the safe backend message (e.g. "Invalid email or password").
      // Never surface raw error internals / stack traces.
      setError(
        err instanceof Error && /Unauthorized/.test(err.message)
          ? "邮箱或密码错误"
          : "登录失败，请稍后重试"
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm py-20">
      <h1 className="mb-6 text-center text-2xl font-bold">Personal AI Assistant</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="mb-1 block text-sm text-gray-300">邮箱</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-gray-300">密码</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            className="w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-blue-500"
          />
        </div>
        {error && (
          <p className="text-sm text-red-300">{error}</p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? "登录中…" : "登录"}
        </button>
      </form>
      <p className="mt-4 text-center text-sm text-gray-400">
        没有账号？
        <Link href="/register" className="ml-1 text-blue-400 hover:underline">
          注册
        </Link>
      </p>
    </div>
  );
}
