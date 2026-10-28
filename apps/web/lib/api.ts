export type Item = Record<string, unknown> & { id: string };
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};
export type Department = { id: string; name: string };
export type User = {
  id: string;
  email: string;
  name: string;
  roles: string[];
  department_ids: string[];
  permissions: string[];
  departments: Department[];
  csrf_token: string;
};
export type Agent = {
  id: string;
  name: string;
  department_id: string;
  description: string;
  provider: string;
  model: string;
  tools: string[];
  system_prompt: string;
  status: string;
  max_tokens: number;
  max_iterations?: number;
  budget_usd: string;
  prompt_version: number;
};
export type Citation = {
  document_id: string;
  document_name: string;
  chunk_id: string;
  location: string;
  excerpt: string;
};
export type Message = {
  id: string;
  role: string;
  content: string;
  citations?: Citation[];
  created_at?: string;
};
export type Conversation = {
  id: string;
  title: string;
  agent_id: string;
  messages: Message[];
};
export type Document = {
  id: string;
  owner_id?: string;
  name?: string;
  filename?: string;
  department_id: string;
  visibility: string;
  status: string;
  created_at: string;
  text?: string;
  preview?: string;
  extracted_text?: string;
  error_code?: string;
  versions?: unknown[];
  error?: string;
};
export type Approval = {
  id: string;
  title: string;
  status: string;
  resource_type: string;
  resource_id: string;
  department_id: string;
  expires_at: string;
  created_at: string;
  payload: unknown;
  decisions?: unknown[];
};
export type Overview = {
  active_agents: number;
  workflows_completed: number;
  pending_approvals: number;
  documents_processed: number;
  failed_executions: number;
  estimated_minutes_saved: number;
  estimate_method: string;
  activity: { date: string; completed: number; failed: number }[];
  departments: { name: string; executions: number }[];
  provider_configured: boolean;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
let csrfToken = "";
export function setCsrfToken(token: string) {
  csrfToken = token;
}
export function clearSession() {
  setCsrfToken("");
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event("ef-session-expired"));
}
export function requestHeaders(body?: unknown, method = "GET"): HeadersInit {
  return {
    ...(body && !(body instanceof FormData)
      ? { "Content-Type": "application/json" }
      : {}),
    ...(!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken
      ? { "X-CSRF-Token": csrfToken }
      : {}),
  };
}
export async function responseError(response: Response) {
  if (response.status === 401) clearSession();
  const body = await response.json().catch(() => null);
  const detail = body?.error?.message ?? body?.detail ?? body?.message;
  const message =
    typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((d: { msg?: string }) => d.msg).join("; ")
        : response.status === 401
          ? "Your session has expired. Please sign in again."
          : `Request failed (${response.status}). Please try again.`;
  const fields = body?.error?.fields;
  const fieldDetails = Array.isArray(fields)
    ? fields
        .map(
          (field: {
            loc?: unknown[];
            msg?: string;
            field?: string;
            message?: string;
          }) =>
            `${field.field || field.loc?.filter((part: unknown) => part !== "body").join(".") || "Field"}: ${field.message || field.msg || "Invalid value"}`,
        )
        .join("; ")
    : "";
  return new ApiError(
    response.status,
    fieldDetails ? `${message} ${fieldDetails}` : message,
  );
}
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    idempotencyKey?: string;
  } = {},
): Promise<T> {
  const { body, method = "GET", signal } = options;
  const response = await fetch(`/api/v1${path}`, {
    method,
    credentials: "include",
    headers: {
      ...requestHeaders(body, method),
      ...(options.idempotencyKey
        ? { "Idempotency-Key": options.idempotencyKey }
        : {}),
    },
    ...(body !== undefined
      ? { body: body instanceof FormData ? body : JSON.stringify(body) }
      : {}),
    signal,
  });
  if (!response.ok) {
    throw await responseError(response);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
export function list<T>(data: Page<T> | T[] | undefined): T[] {
  return Array.isArray(data) ? data : (data?.items ?? []);
}
export function human(value: unknown): string {
  return String(value ?? "—").replaceAll("_", " ");
}
export function dateTime(value: unknown): string {
  if (!value) return "—";
  const d = new Date(String(value));
  return Number.isNaN(d.getTime())
    ? String(value)
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(d);
}
export function jsonText(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
export type StreamEvent = { event: string; data: Record<string, unknown> };
/** Parses SSE across arbitrary network chunk boundaries, including CRLF and multiline data. */
export async function consumeEvents(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: StreamEvent) => void,
) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  function dispatch(frame: string) {
    let event = "message";
    const parts: string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) parts.push(line.slice(5).trimStart());
    }
    if (parts.length) {
      const data = JSON.parse(parts.join("\n"));
      onEvent({ event, data });
    }
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        dispatch(buffer.slice(0, boundary.index));
        buffer = buffer.slice(boundary.index + boundary[0].length);
      }
      if (done) break;
    }
    if (buffer.trim()) dispatch(buffer);
  } catch (error) {
    await reader.cancel(error).catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }
}

export type BackgroundJob<T = unknown> = {
  id: string;
  kind: string;
  status:
    | "queued"
    | "running"
    | "retrying"
    | "completed"
    | "dead_letter"
    | "cancelled";
  attempts: number;
  error_code?: string;
  error_message?: string;
  result: T | null;
  created_at: string;
  updated_at: string;
};
export async function waitForJob<T>(
  jobId: string,
  options: {
    onProgress?: (job: BackgroundJob<T>) => void;
    signal?: AbortSignal;
    intervalMs?: number;
    maxPolls?: number;
  } = {},
): Promise<T> {
  const { onProgress, signal, intervalMs = 1500, maxPolls = 200 } = options;
  for (let i = 0; i < maxPolls; i++) {
    signal?.throwIfAborted();
    const job = await api<BackgroundJob<T>>(
      `/jobs/${encodeURIComponent(jobId)}`,
      { signal },
    );
    onProgress?.(job);
    if (job.status === "completed") {
      if (job.result === null || job.result === undefined)
        throw new Error(
          `Job ${jobId} completed without a result. Inspect its status before retrying.`,
        );
      return job.result;
    }
    if (job.status === "dead_letter")
      throw new Error(
        `Processing failed: ${job.error_message || human(job.error_code || "job failure")}. Job ${jobId} is available in Background jobs.`,
      );
    if (job.status === "cancelled")
      throw new Error(`Job ${jobId} was cancelled.`);
    if (i + 1 < maxPolls)
      await new Promise<void>((resolve, reject) => {
        const abort = () => {
          clearTimeout(timer);
          reject(
            signal?.reason || new DOMException("Request aborted", "AbortError"),
          );
        };
        const timer = setTimeout(() => {
          signal?.removeEventListener("abort", abort);
          resolve();
        }, intervalMs);
        signal?.addEventListener("abort", abort, { once: true });
      });
  }
  throw new Error(
    `Job ${jobId} is still processing. Check Background jobs for its result; do not resubmit the same request.`,
  );
}
export async function businessRequest<T>(
  path: string,
  body: unknown,
  onProgress?: (job: BackgroundJob<T>) => void,
): Promise<T> {
  const result = await api<T | { job_id: string; status: string }>(path, {
    method: "POST",
    body,
    idempotencyKey: crypto.randomUUID(),
  });
  if (result && typeof result === "object" && "job_id" in result) {
    return waitForJob<T>(String(result.job_id), { onProgress });
  }
  if (
    result &&
    typeof result === "object" &&
    "id" in result &&
    "kind" in result &&
    "attempts" in result &&
    "status" in result
  ) {
    return waitForJob<T>(String(result.id), { onProgress });
  }
  return result as T;
}
