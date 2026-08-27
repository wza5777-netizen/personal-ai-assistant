"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiClient, Task } from "@/lib/api-client";

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

/** Format a datetime into a friendly relative label. */
function formatDueTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfTarget = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dayDiff = Math.round(
    (startOfTarget.getTime() - startOfToday.getTime()) / 86_400_000,
  );
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes(),
  ).padStart(2, "0")}`;

  if (dayDiff === 0) return `今天 ${hm}`;
  if (dayDiff === 1) return `明天 ${hm}`;
  if (dayDiff === -1) return `昨天 ${hm}`;
  if (d.getFullYear() === now.getFullYear())
    return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}

/** Format a datetime used for "created/completed at" meta lines. */
function formatMetaTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes(),
  ).padStart(2, "0")}`;
  if (d.toDateString() === now.toDateString()) return `今天 ${hm}`;
  if (d.getFullYear() === now.getFullYear())
    return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}

const PRIORITY_LABELS: Record<string, string> = {
  low: "低",
  normal: "普通",
  medium: "中",
  high: "高",
  urgent: "紧急",
};

/** Only prominent priorities get a visible badge. */
function PriorityBadge({ priority }: { priority: string }) {
  const isProminent = priority === "high" || priority === "urgent";
  if (!isProminent) return null;
  const styles =
    priority === "urgent"
      ? "border-red-500/30 bg-red-500/10 text-red-400"
      : "border-orange-500/30 bg-orange-500/10 text-orange-400";
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-xs ${styles}`}
    >
      {PRIORITY_LABELS[priority] ?? priority}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/* Sub-components                                                      */
/* ------------------------------------------------------------------ */

function TaskCardSkeleton() {
  return (
    <div className="animate-pulse rounded-lg border border-white/5 p-4">
      <div className="flex items-center gap-3">
        <div className="h-5 w-5 rounded-full bg-white/10" />
        <div className="h-4 flex-1 rounded bg-white/10" />
      </div>
      <div className="mt-3 h-3 w-3/4 rounded bg-white/5" />
      <div className="mt-4 h-3 w-1/2 rounded bg-white/5" />
    </div>
  );
}

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}

function ConfirmDialog({
  title,
  message,
  confirmLabel = "删除",
  onConfirm,
  onCancel,
  busy = false,
}: ConfirmDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-sm rounded-xl border border-white/10 bg-[#1a1a1e] p-6 shadow-xl">
        <h3 className="text-base font-semibold text-gray-100">{title}</h3>
        <p className="mt-2 text-sm text-gray-400">{message}</p>
        <div className="mt-6 flex justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={busy}
            className="rounded-md px-4 py-2 text-sm text-gray-300 transition-colors hover:bg-white/5 disabled:opacity-50"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="rounded-md bg-red-600/90 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-50"
          >
            {busy ? "删除中…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [tab, setTab] = useState<"pending" | "completed">("pending");
  const [query, setQuery] = useState("");

  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);

  const [menuFor, setMenuFor] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Task | null>(null);

  const [showEditor, setShowEditor] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const menuRef = useRef<HTMLDivElement | null>(null);

  const fetchTasks = useCallback(async () => {
    setLoadError(null);
    try {
      const data = await apiClient.listTasks();
      setTasks(data);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "加载任务失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  /* Close the "..." menu when clicking elsewhere. */
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuFor(null);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const pendingTasks = useMemo(
    () => tasks.filter((t) => t.status === "pending"),
    [tasks],
  );
  const completedTasks = useMemo(
    () => tasks.filter((t) => t.status === "completed"),
    [tasks],
  );

  const visibleTasks = useMemo(() => {
    const source = tab === "pending" ? pendingTasks : completedTasks;
    const q = query.trim().toLowerCase();
    if (!q) return source;
    return source.filter(
      (t) =>
        t.title.toLowerCase().includes(q) ||
        (t.description ?? "").toLowerCase().includes(q),
    );
  }, [tab, query, pendingTasks, completedTasks]);

  const markBusy = useCallback((id: number, busy: boolean) => {
    setBusyIds((prev) => {
      const next = new Set(prev);
      if (busy) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const runAction = useCallback(
    async (
      id: number,
      fn: () => Promise<unknown>,
      onDone?: (task: Task) => void,
    ) => {
      setActionError(null);
      markBusy(id, true);
      try {
        const result = await fn();
        if (result && typeof result === "object" && "id" in result) {
          onDone?.(result as Task);
        }
        // Refresh to keep counts/timestamps authoritative.
        const data = await apiClient.listTasks();
        setTasks(data);
        setMenuFor(null);
      } catch (e) {
        setActionError(e instanceof Error ? e.message : "操作失败，请重试");
        // Re-fetch to restore optimistic/authoritative state on failure.
        const data = await apiClient.listTasks();
        setTasks(data);
      } finally {
        markBusy(id, false);
      }
    },
    [markBusy],
  );

  const handleComplete = useCallback(
    (task: Task) => {
      void runAction(task.id, () => apiClient.completeTask(task.id));
    },
    [runAction],
  );

  const handleRestore = useCallback(
    (task: Task) => {
      void runAction(task.id, () =>
        apiClient.updateTask(task.id, { status: "pending" }),
      );
    },
    [runAction],
  );

  const handleDelete = useCallback(
    (task: Task) => {
      setConfirmDelete(task);
      setMenuFor(null);
    },
    [],
  );

  const confirmDeleteAction = useCallback(async () => {
    if (!confirmDelete) return;
    setActionError(null);
    markBusy(confirmDelete.id, true);
    try {
      await apiClient.deleteTask(confirmDelete.id);
      setConfirmDelete(null);
      const data = await apiClient.listTasks();
      setTasks(data);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "删除失败，请重试");
      setConfirmDelete(null);
    } finally {
      markBusy(confirmDelete.id, false);
    }
  }, [confirmDelete, markBusy]);

  const openCreate = useCallback(() => {
    setEditingTask(null);
    setSaveError(null);
    setShowEditor(true);
  }, []);

  const openEdit = useCallback(
    (task: Task) => {
      setEditingTask(task);
      setSaveError(null);
      setShowEditor(true);
      setMenuFor(null);
    },
    [],
  );

  const closeEditor = useCallback(() => setShowEditor(false), []);

  const handleSave = useCallback(
    async (input: { title: string; description: string; due_time: string }) => {
      setSaving(true);
      setSaveError(null);
      try {
        const payload = {
          title: input.title,
          description: input.description || null,
          due_time: input.due_time || null,
        };
        if (editingTask) {
          await apiClient.updateTask(editingTask.id, payload);
        } else {
          await apiClient.createTask(payload);
        }
        setShowEditor(false);
        setSaving(false);
        const data = await apiClient.listTasks();
        setTasks(data);
      } catch (e) {
        setSaveError(e instanceof Error ? e.message : "保存失败，请重试");
        setSaving(false);
      }
    },
    [editingTask],
  );

  const pendingCount = pendingTasks.length;
  const completedCount = completedTasks.length;
  const isEmpty = visibleTasks.length === 0 && !query.trim();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">任务</h1>
          <p className="mt-1 text-sm text-gray-400">
            管理今天要做的事情，也可以直接在对话中让 AI 创建和更新任务。
          </p>
        </div>
        <button
          onClick={openCreate}
          className="shrink-0 self-start rounded-md bg-white/10 px-4 py-2 text-sm font-medium text-gray-100 transition-colors hover:bg-white/15 sm:self-auto"
        >
          + 新建任务
        </button>
      </div>

      {/* Stats */}
      <div className="flex gap-6 text-sm">
        <div className="flex items-baseline gap-2">
          <span className="text-xs uppercase tracking-wide text-gray-500">
            待完成
          </span>
          <span className="text-lg font-semibold text-gray-100">
            {pendingCount}
          </span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-xs uppercase tracking-wide text-gray-500">
            已完成
          </span>
          <span className="text-lg font-semibold text-gray-100">
            {completedCount}
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-white/10">
        <button
          onClick={() => setTab("pending")}
          className={`-mb-px border-b-2 px-4 py-2 text-sm transition-colors ${
            tab === "pending"
              ? "border-white/80 text-gray-100"
              : "border-transparent text-gray-400 hover:text-gray-200"
          }`}
        >
          待完成 {pendingCount}
        </button>
        <button
          onClick={() => setTab("completed")}
          className={`-mb-px border-b-2 px-4 py-2 text-sm transition-colors ${
            tab === "completed"
              ? "border-white/80 text-gray-100"
              : "border-transparent text-gray-400 hover:text-gray-200"
          }`}
        >
          已完成 {completedCount}
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-500">
          <svg
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M21 21l-4.35-4.35M17 10.5a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z"
            />
          </svg>
        </span>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索任务…"
          className="w-full rounded-md border border-white/10 bg-white/5 py-2 pl-9 pr-3 text-sm text-gray-100 placeholder-gray-500 outline-none transition-colors focus:border-white/25 focus:bg-white/10"
        />
      </div>

      {/* Action error */}
      {actionError && (
        <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {actionError}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-3">
          <TaskCardSkeleton />
          <TaskCardSkeleton />
          <TaskCardSkeleton />
        </div>
      )}

      {/* Load error */}
      {!loading && loadError && (
        <div className="rounded-lg border border-white/10 p-6 text-center">
          <p className="text-sm text-red-400">加载失败：{loadError}</p>
          <button
            onClick={() => {
              setLoading(true);
              fetchTasks();
            }}
            className="mt-4 rounded-md bg-white/10 px-4 py-2 text-sm text-gray-100 transition-colors hover:bg-white/15"
          >
            重试
          </button>
        </div>
      )}

      {/* Empty states */}
      {!loading && !loadError && isEmpty && (
        <div className="rounded-lg border border-dashed border-white/10 p-10 text-center">
          {tab === "pending" ? (
            <>
              <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-white/5 text-xl text-gray-400">
                ✓
              </div>
              <p className="mt-3 text-sm text-gray-300">
                当前没有待完成任务
              </p>
              <p className="mx-auto mt-1 max-w-xs text-xs text-gray-500">
                可以去对话中告诉 AI：“帮我创建一个明天下午提交周报的任务”
              </p>
              <a
                href="/chat"
                className="mt-5 inline-block rounded-md bg-white/10 px-4 py-2 text-sm font-medium text-gray-100 transition-colors hover:bg-white/15"
              >
                去对话
              </a>
            </>
          ) : (
            <>
              <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-white/5 text-xl text-gray-400">
                ✓
              </div>
              <p className="mt-3 text-sm text-gray-300">还没有已完成的任务</p>
              <p className="mx-auto mt-1 max-w-xs text-xs text-gray-500">
                完成任务后会显示在这里。
              </p>
            </>
          )}
        </div>
      )}

      {/* Search no-results */}
      {!loading && !loadError && !isEmpty && visibleTasks.length === 0 && (
        <div className="rounded-lg border border-dashed border-white/10 p-10 text-center">
          <p className="text-sm text-gray-300">没有找到匹配的任务</p>
          <p className="mt-1 text-xs text-gray-500">
            换个关键词试试，或清空搜索。
          </p>
        </div>
      )}

      {/* Task list */}
      {!loading && !loadError && visibleTasks.length > 0 && (
        <ul className="space-y-3">
          {visibleTasks.map((task) => {
            const busy = busyIds.has(task.id);
            const isCompleted = task.status === "completed";
            return (
              <li
                key={task.id}
                className={`group relative rounded-lg border border-white/10 p-4 transition-colors hover:border-white/20 hover:bg-white/[0.03] ${
                  isCompleted ? "opacity-70" : ""
                }`}
              >
                <div className="flex items-start gap-3">
                  {/* Complete / restored state icon */}
                  {isCompleted ? (
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs text-gray-300">
                      ✓
                    </span>
                  ) : (
                    <button
                      onClick={() => handleComplete(task)}
                      disabled={busy}
                      aria-label="标记完成"
                      className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-white/30 text-transparent transition-all hover:border-white/60 hover:bg-white/10 disabled:opacity-50"
                    >
                      {busy ? (
                        <span className="h-3 w-3 animate-spin rounded-full border border-white/30 border-t-white/80" />
                      ) : (
                        "✓"
                      )}
                    </button>
                  )}

                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <h3
                        className={`text-sm font-medium text-gray-100 ${
                          isCompleted ? "line-through" : ""
                        }`}
                      >
                        {task.title}
                      </h3>

                      {/* More actions */}
                      <div className="relative shrink-0" ref={menuRef}>
                        <button
                          onClick={() =>
                            setMenuFor(menuFor === task.id ? null : task.id)
                          }
                          disabled={busy}
                          aria-label="更多操作"
                          className="rounded p-1 text-gray-500 transition-colors hover:bg-white/10 hover:text-gray-200 disabled:opacity-50"
                        >
                          <svg
                            className="h-4 w-4"
                            fill="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <circle cx="12" cy="5" r="1.7" />
                            <circle cx="12" cy="12" r="1.7" />
                            <circle cx="12" cy="19" r="1.7" />
                          </svg>
                        </button>

                        {menuFor === task.id && (
                          <div className="absolute right-0 top-8 z-20 w-36 overflow-hidden rounded-md border border-white/10 bg-[#1a1a1e] shadow-lg">
                            {isCompleted ? (
                              <button
                                onClick={() => handleRestore(task)}
                                disabled={busy}
                                className="block w-full px-4 py-2 text-left text-sm text-gray-200 transition-colors hover:bg-white/5 disabled:opacity-50"
                              >
                                恢复
                              </button>
                            ) : (
                              <>
                                <button
                                  onClick={() => openEdit(task)}
                                  className="block w-full px-4 py-2 text-left text-sm text-gray-200 transition-colors hover:bg-white/5"
                                >
                                  编辑
                                </button>
                                <button
                                  onClick={() => handleComplete(task)}
                                  disabled={busy}
                                  className="block w-full px-4 py-2 text-left text-sm text-gray-200 transition-colors hover:bg-white/5 disabled:opacity-50"
                                >
                                  完成
                                </button>
                              </>
                            )}
                            <button
                              onClick={() => handleDelete(task)}
                              className="block w-full border-t border-white/10 px-4 py-2 text-left text-sm text-red-400 transition-colors hover:bg-red-500/10"
                            >
                              删除
                            </button>
                          </div>
                        )}
                      </div>
                    </div>

                    {task.description && (
                      <p
                        className={`mt-1 text-sm ${
                          isCompleted ? "text-gray-500" : "text-gray-400"
                        }`}
                      >
                        {task.description}
                      </p>
                    )}

                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                      <PriorityBadge priority={task.priority} />
                      {task.due_time && (
                        <span>
                          截止 {formatDueTime(task.due_time)}
                        </span>
                      )}
                      <span>
                        {isCompleted
                          ? task.completed_at
                            ? `完成于 ${formatMetaTime(task.completed_at)}`
                            : `完成于 ${formatMetaTime(task.updated_at)}`
                          : `创建于 ${formatMetaTime(task.created_at)}`}
                      </span>
                    </div>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Create / Edit modal */}
      {showEditor && (
        <TaskEditorModal
          task={editingTask}
          saving={saving}
          error={saveError}
          onClose={closeEditor}
          onSave={handleSave}
        />
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <ConfirmDialog
          title="删除任务"
          message={`确定要删除「${confirmDelete.title}」吗？此操作无法撤销。`}
          confirmLabel="删除"
          busy={busyIds.has(confirmDelete.id)}
          onConfirm={confirmDeleteAction}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Create / Edit modal                                                 */
/* ------------------------------------------------------------------ */

interface TaskEditorModalProps {
  task: Task | null;
  saving: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (input: {
    title: string;
    description: string;
    due_time: string;
  }) => Promise<void>;
}

function TaskEditorModal({
  task,
  saving,
  error,
  onClose,
  onSave,
}: TaskEditorModalProps) {
  const [title, setTitle] = useState(task?.title ?? "");
  const [description, setDescription] = useState(task?.description ?? "");
  const [dueTime, setDueTime] = useState(() => {
    if (!task?.due_time) return "";
    // Convert to local yyyy-MM-ddTHH:mm for the datetime-local input.
    const d = new Date(task.due_time);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
      d.getHours(),
    )}:${pad(d.getMinutes())}`;
  });

  const canSubmit = title.trim().length > 0 && !saving;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md rounded-xl border border-white/10 bg-[#1a1a1e] p-6 shadow-xl">
        <h3 className="text-base font-semibold text-gray-100">
          {task ? "编辑任务" : "新建任务"}
        </h3>
        <p className="mt-1 text-xs text-gray-500">
          也可以直接在对话中告诉 AI 创建任务。
        </p>

        <form
          className="mt-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) void onSave({ title, description, due_time: dueTime });
          }}
        >
          <div>
            <label className="mb-1 block text-xs text-gray-400">标题 *</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={256}
              autoFocus
              className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-gray-100 outline-none transition-colors focus:border-white/25 focus:bg-white/10"
              placeholder="要做什么？"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs text-gray-400">描述</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full resize-none rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-gray-100 outline-none transition-colors focus:border-white/25 focus:bg-white/10"
              placeholder="补充细节（可选）"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs text-gray-400">截止时间</label>
            <input
              type="datetime-local"
              value={dueTime}
              onChange={(e) => setDueTime(e.target.value)}
              className="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-gray-100 outline-none transition-colors [color-scheme:dark] focus:border-white/25 focus:bg-white/10"
            />
          </div>

          {error && (
            <p className="text-sm text-red-400">{error}</p>
          )}

          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="rounded-md px-4 py-2 text-sm text-gray-300 transition-colors hover:bg-white/5 disabled:opacity-50"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="rounded-md bg-white/10 px-4 py-2 text-sm font-medium text-gray-100 transition-colors hover:bg-white/15 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "保存中…" : task ? "保存" : "创建"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
