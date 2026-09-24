// 后端 API 封装：所有请求集中在这里，组件只调用语义化函数
import type {
  DependencyGraph,
  IngestResult,
  TraceSummary,
  TraceTree,
} from "./types";

const BASE = "/api";

async function getJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.error) detail = JSON.stringify(body.error);
    } catch {
      // 非 JSON 错误体，保留状态码文本
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export function searchTraces(params: {
  trace_id?: string;
  service?: string;
  limit?: number;
}): Promise<TraceSummary[]> {
  const search = new URLSearchParams();
  if (params.trace_id) search.set("trace_id", params.trace_id);
  if (params.service) search.set("service", params.service);
  if (params.limit) search.set("limit", String(params.limit));
  return getJson<TraceSummary[]>(`${BASE}/traces?${search.toString()}`);
}

export function getTrace(traceId: string): Promise<TraceTree> {
  return getJson<TraceTree>(`${BASE}/traces/${encodeURIComponent(traceId)}`);
}

export function getDependencyGraph(window: string): Promise<DependencyGraph> {
  return getJson<DependencyGraph>(`${BASE}/dependencies?window=${window}`);
}

export function listWindows(): Promise<{
  windows: { key: string; seconds: number }[];
  default: string;
}> {
  return getJson(`${BASE}/windows`);
}

export async function reportSpans(spans: unknown[]): Promise<IngestResult> {
  const resp = await fetch(`${BASE}/spans`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spans }),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(body?.error ? JSON.stringify(body.error, null, 2) : resp.statusText);
  }
  return body as IngestResult;
}
