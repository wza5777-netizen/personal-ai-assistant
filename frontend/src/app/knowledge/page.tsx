"use client";

import { useEffect, useState } from "react";
import { apiClient, Document } from "@/lib/api-client";

const ACCEPT = ".pdf,.txt,.md";

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);

  const load = () => {
    apiClient
      .listDocuments()
      .then(setDocuments)
      .catch((e) => setError(e.message ?? "加载失败"))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const onUpload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await apiClient.uploadDocument(file);
      setFile(null);
      (document.getElementById("doc-input") as HTMLInputElement).value = "";
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">知识库</h1>

      <div className="rounded-lg border border-white/10 p-4">
        <p className="mb-3 text-sm text-gray-400">
          上传 PDF / TXT / Markdown 文档，Agent 会在对话中自动检索这些内容。
        </p>
        <div className="flex gap-2">
          <input
            id="doc-input"
            type="file"
            accept={ACCEPT}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-blue-500"
          />
          <button
            onClick={onUpload}
            disabled={uploading || !file}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {uploading ? "上传中…" : "上传"}
          </button>
        </div>
        {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
      </div>

      <h2 className="text-lg font-semibold">已上传文档</h2>
      {loading && <p className="text-sm text-gray-500">加载中…</p>}
      {!loading && documents.length === 0 && (
        <p className="text-sm text-gray-500">暂无文档。</p>
      )}
      <ul className="space-y-3">
        {documents.map((d) => (
          <li key={d.id} className="rounded-lg border border-white/10 p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">{d.filename}</span>
              <span className="text-xs text-gray-500">{d.content_type}</span>
            </div>
            <div className="mt-1 text-xs text-gray-500">
              {d.chunk_count} 个片段 · {new Date(d.created_at).toLocaleString()}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
