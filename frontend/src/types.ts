// 与后端 API 对齐的类型定义

export interface TraceSummary {
  trace_id: string;
  span_count: number;
  services: string[];
  start_time: string;
  duration_ms: number;
  error_count: number;
}

export interface SpanNode {
  span_id: string;
  parent_span_id: string | null;
  effective_parent_id: string | null;
  service: string;
  start_time: string;
  end_time: string;
  start_ns: number;
  end_ns: number;
  duration_ms: number;
  status_code: number;
  is_error: boolean;
  children: SpanNode[];
  on_critical_path?: boolean;
  awaiting_parent?: boolean;
  parent_missing?: boolean;
  placeholder?: boolean;
  label?: string;
}

export interface CriticalPath {
  span_ids: string[];
  total_duration_ms: number;
}

export interface ServiceShare {
  service: string;
  duration_ms: number;
  share: number;
}

export interface TraceTree {
  trace_id: string;
  roots: SpanNode[];
  span_count: number;
  has_missing_parent: boolean;
  critical_path: CriticalPath;
  service_share: ServiceShare[];
}

export interface GraphNode {
  service: string;
  call_count: number;
  called_count: number;
  total_calls: number;
}

export interface GraphEdge {
  caller: string;
  callee: string;
  count: number;
  avg_duration_ms: number;
  cyclic: boolean;
}

export interface DependencyGraph {
  window: string;
  window_seconds: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  has_cycle: boolean;
  cyclic_edges: string[];
}

export interface IngestResult {
  accepted: number;
  duplicates: number;
  resolved_waits: number;
  timed_out: number;
  trace_ids: string[];
}

export type WsEvent =
  | { type: "hello"; data: { msg: string } }
  | { type: "spans.ingested"; data: IngestResult }
  | { type: "spans.timeout"; data: { timed_out: number } }
  | { type: "graph.updated"; data: { windows: string[] } };
