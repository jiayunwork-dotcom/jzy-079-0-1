"""业务编排层：把存储、拼树、依赖图、推送串起来，供路由与测试共用。"""
from __future__ import annotations

from .assembler import TreeAssembler
from .config import DEPENDENCY_WINDOWS_SECONDS
from .dependencies import DependencyGraphBuilder
from .errors import BadRequestError
from .events import EventHub
from .repositories.db import Database
from .schemas import ValidatedSpan
from .timeutil import now_ns


class TraceService:
    def __init__(self, db: Database, event_hub: EventHub | None = None):
        self.db = db
        self.assembler = TreeAssembler(db)
        self.graph_builder = DependencyGraphBuilder(db)
        self.events = event_hub or EventHub()

    # ------------------------------------------------------------ 上报
    def ingest_spans(
        self, spans: list[ValidatedSpan], at_ns: int | None = None
    ) -> dict:
        arrival = at_ns if at_ns is not None else now_ns()
        with self.db.lock:
            result = self.assembler.ingest(spans, at_ns=arrival)
        payload = {
            "accepted": result.accepted,
            "duplicates": result.duplicates,
            "resolved_waits": result.resolved_waits,
            "timed_out": result.timed_out,
            "trace_ids": result.affected_traces,
        }
        if result.accepted:
            self.events.publish("spans.ingested", payload)
            self.events.publish("graph.updated", {"windows": list(DEPENDENCY_WINDOWS_SECONDS)})
        return payload

    def sweep_timeouts(self, now: int | None = None) -> int:
        n = self.assembler.sweep_timeouts(now)
        if n:
            self.events.publish("spans.timeout", {"timed_out": n})
        return n

    # ------------------------------------------------------------ 查询
    def get_trace(self, trace_id: str) -> dict:
        with self.db.lock:
            tree = self.assembler.build_trace(trace_id)
        if tree is None:
            from .errors import NotFoundError

            raise NotFoundError({"message": f"追踪 {trace_id} 不存在"})
        return tree

    def search_traces(
        self,
        trace_id: str | None = None,
        service: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        rows = self.assembler.spans.list_traces(trace_id, service, limit * 4)
        summaries: dict[str, dict] = {}
        for r in rows:
            tid = r["trace_id"]
            entry = summaries.setdefault(
                tid,
                {
                    "trace_id": tid,
                    "span_count": 0,
                    "services": set(),
                    "start_ns": r["start_ns"],
                    "end_ns": r["end_ns"],
                    "error_count": 0,
                    "last_arrival_ns": r["arrival_ns"],
                },
            )
            entry["span_count"] += 1
            entry["services"].add(r["service"])
            entry["start_ns"] = min(entry["start_ns"], r["start_ns"])
            entry["end_ns"] = max(entry["end_ns"], r["end_ns"])
            entry["last_arrival_ns"] = max(entry["last_arrival_ns"], r["arrival_ns"])
            if r["status_code"] >= 500:
                entry["error_count"] += 1

        from .timeutil import ns_to_iso

        result = []
        for entry in summaries.values():
            duration_ms = round(
                (entry["end_ns"] - entry["start_ns"]) / 1_000_000, 3
            )
            result.append(
                {
                    "trace_id": entry["trace_id"],
                    "span_count": entry["span_count"],
                    "services": sorted(entry["services"]),
                    "start_time": ns_to_iso(entry["start_ns"]),
                    "duration_ms": duration_ms,
                    "error_count": entry["error_count"],
                }
            )
        result.sort(key=lambda e: e["start_time"], reverse=True)
        return result[:limit]

    def get_dependency_graph(self, window: str, now: int | None = None) -> dict:
        if window not in DEPENDENCY_WINDOWS_SECONDS:
            raise BadRequestError(
                {
                    "message": f"不支持的时间窗口 {window!r}",
                    "allowed": list(DEPENDENCY_WINDOWS_SECONDS),
                }
            )
        with self.db.lock:
            graph = self.graph_builder.build(
                DEPENDENCY_WINDOWS_SECONDS[window], now=now
            )
        graph["window"] = window
        return graph
