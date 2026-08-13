// API client for the backend. Reads base URL from NEXT_PUBLIC_API_BASE_URL.

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export interface ChatRequest {
  user_id: string;
  message: string;
}

export interface ChatResponse {
  response: string;
}

export interface HealthResponse {
  status: string;
}

/** A streamed agent event (see backend app/context/stream.py). */
export type StreamEventType =
  | "agent_start"
  | "tool_call"
  | "tool_result"
  | "token"
  | "agent_end"
  | "error"
  | "done";

export interface StreamEvent {
  type: StreamEventType;
  run_id?: string;
  timestamp?: number;
  // token
  content?: string;
  // tool_call
  tool_name?: string;
  arguments?: Record<string, unknown>;
  risk_level?: string;
  tool_call_id?: string;
  // tool_result
  status?: string;
  result?: unknown;
  approval_id?: string;
  // agent_start / agent_end
  user_id?: string;
  response?: string;
  // error
  message?: string;
}

export interface ApprovalItem {
  id: string;
  user_id: string;
  tool_name: string;
  arguments: Record<string, unknown> | string;
  status: "pending" | "approved" | "rejected";
  conversation_id?: string | null;
  decision_reason?: string | null;
  created_at: string;
  decided_at?: string | null;
}

export interface ApprovalDecision {
  status: "approved" | "rejected";
  decision_reason?: string | null;
}

export interface Task {
  id: number;
  user_id: string;
  title: string;
  description: string | null;
  status: string;
  priority: string;
  due_time: string | null;
  created_at: string;
  updated_at: string;
}

export interface CalendarEvent {
  id: number;
  user_id: string;
  title: string;
  description: string | null;
  start_time: string;
  end_time: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Memory {
  id: number;
  user_id: string;
  type: string;
  content: string;
  importance: number;
  created_at: string;
  updated_at: string;
}

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export interface Document {
  id: number;
  user_id: string;
  filename: string;
  content_type: string;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

// ---------- Observability (Admin Runs) ----------
export interface RunSummary {
  run_id: string;
  user_id: string;
  conversation_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  latency_ms: number | null;
  llm_calls: number;
  tool_calls: number;
  tool_failures: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
}

export interface RunListResponse {
  total: number;
  limit: number;
  offset: number;
  runs: RunSummary[];
}

export interface TraceEventView {
  sequence: number;
  event_type: string;
  timestamp: string;
  tool_name: string | null;
  status: string | null;
  details: Record<string, unknown> | null;
}

export interface ToolCallView {
  sequence: number;
  tool_name: string;
  status: string | null;
  arguments: Record<string, unknown> | null;
  result_ok: boolean | null;
}

export interface RunDetail {
  run_id: string;
  user_id: string;
  conversation_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  latency_ms: number | null;
  prompt: string | null;
  final_response: string | null;
  error: string | null;
  llm_calls: number;
  tool_calls: number;
  tool_failures: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  timeline: TraceEventView[];
  tool_calls_detail: ToolCallView[];
}

// Admin token is cached in sessionStorage for the observability pages.
function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem("admin_token");
}

function setAdminToken(token: string): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem("admin_token", token);
}

async function authRequest<T>(path: string): Promise<T> {
  const token = getAdminToken();
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (res.status === 401) {
    // Try to obtain a fresh dev token, then retry once.
    try {
      const t = await request<{ access_token: string }>("/api/v1/admin/token");
      setAdminToken(t.access_token);
      const retry = await fetch(`${API_BASE_URL}${path}`, {
        headers: { Authorization: `Bearer ${t.access_token}` },
      });
      if (!retry.ok) throw new Error(`Request failed: ${retry.status}`);
      return (await retry.json()) as T;
    } catch {
      throw new Error("Admin authentication failed");
    }
  }
  if (!res.ok) throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export const apiClient = {
  health: () => request<HealthResponse>("/health"),
  chat: (payload: ChatRequest) =>
    request<ChatResponse>("/api/v1/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  /** Stream a chat run over SSE. Calls ``onEvent`` for each parsed event. */
  streamChat: async (
    payload: ChatRequest,
    onEvent: (event: StreamEvent) => void
  ): Promise<void> => {
    const res = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok || !res.body) {
      throw new Error(`Stream failed: ${res.status} ${res.statusText}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE frames are separated by a blank line.
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const json = line.slice(5).trim();
        if (!json) continue;
        try {
          onEvent(JSON.parse(json) as StreamEvent);
        } catch {
          // Ignore malformed frames.
        }
      }
    }
  },
  listApprovals: (pendingOnly = false) =>
    request<ApprovalItem[]>(
      `/api/v1/approvals${pendingOnly ? "?pending_only=true" : ""}`
    ),
  getApproval: (id: string) => request<ApprovalItem>(`/api/v1/approvals/${id}`),
  decideApproval: (id: string, decision: ApprovalDecision) =>
    request<ApprovalItem>(`/api/v1/approvals/${id}/decision`, {
      method: "POST",
      body: JSON.stringify(decision),
    }),
  listTasks: () => request<Task[]>("/api/v1/tasks"),
  listEvents: () => request<CalendarEvent[]>("/api/v1/calendar/events"),
  listMemories: () => request<Memory[]>("/api/v1/memories"),
  uploadDocument: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_BASE_URL}/api/v1/knowledge/upload`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      throw new Error(`Upload failed: ${res.status} ${res.statusText}`);
    }
    return res.json() as Promise<Document>;
  },
  listDocuments: () => request<Document[]>("/api/v1/knowledge/documents"),
  // ----- Admin observability -----
  obtainAdminToken: () => request<{ access_token: string }>("/api/v1/admin/token"),
  listRuns: (limit = 50, offset = 0, status?: string) =>
    authRequest<RunListResponse>(
      `/api/v1/admin/runs?limit=${limit}&offset=${offset}${status ? `&status=${status}` : ""}`
    ),
  getRun: (runId: string) => authRequest<RunDetail>(`/api/v1/admin/runs/${runId}`),
};
