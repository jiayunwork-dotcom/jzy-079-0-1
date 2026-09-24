"""调用树拼接：乱序等待、重复去重、父缺失占位节点。

状态机（每个有父编号、但父片段尚未到达的片段）：

    新片段到达，父片段不在 spans 表
        -> orphans 记一条 waiting（since=到达时间, timeout=since+最大等待）
    后续某批里父片段到达
        -> waiting 立即 resolved，片段正常挂到父片段下（可乱序归位）
    后台扫描 / 构建前扫描发现 timeout_ns 已过
        -> waiting 变为 timeout（不可逆），片段永久挂到占位节点

占位节点：每个 trace 一个合成节点 MISSING_PARENT_ID，代表「父片段缺失」。
父编号在 spans 表里压根不存在，或等父超时，都归到它下面。

读树时生效的挂载规则（effective parent）：
    1) orphan 记录为 waiting/timeout 的片段 -> 占位节点
       （超时后即使父片段补到也不再改挂，保证「等待超时后才归占位」可验证）
    2) 其余按 parent_span_id；父编号指向不存在片段 -> 占位节点
    3) 父编号为空 -> 根
若存在真实根片段，占位节点作为它的子节点；否则占位节点本身作为根展示。
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import ORPHAN_MAX_WAIT_SECONDS
from .repositories.db import EDGE_BUCKET_NS, Database
from .repositories.dependencies import DependencyRepository
from .repositories.orphans import OrphanRepository
from .repositories.spans import SpanRepository
from .schemas import ValidatedSpan
from .timeutil import NS_PER_SECOND, now_ns, ns_to_iso

# 占位节点的固定编号，不会与真实片段编号冲突
MISSING_PARENT_ID = "__missing_parent__"
MISSING_PARENT_SERVICE = "unknown"


@dataclass
class IngestResult:
    accepted: int          # 本批实际新入库（非重复）的片段数
    duplicates: int        # 被忽略的重复上报数
    resolved_waits: int    # 本批到达后成功归位的等待中子片段数
    timed_out: int         # 本次扫描新超时的片段数
    affected_traces: list[str]


class TreeAssembler:
    def __init__(self, db: Database, max_wait_seconds: float = ORPHAN_MAX_WAIT_SECONDS):
        self._db = db
        self.spans = SpanRepository(db)
        self.orphans = OrphanRepository(db)
        self.dependencies = DependencyRepository(db)
        self._max_wait_ns = int(max_wait_seconds * NS_PER_SECOND)

    # ---------------------------------------------------------------- 上报
    def ingest(self, spans: list[ValidatedSpan], at_ns: int | None = None) -> IngestResult:
        """按上报顺序处理一批片段。必须在 db 锁内调用。"""
        arrival = at_ns if at_ns is not None else now_ns()
        accepted = duplicates = resolved = 0
        traces: set[str] = set()

        for span in spans:
            traces.add(span.trace_id)
            if not self.spans.insert_if_absent(span, arrival):
                # 同一 (trace_id, span_id) 只认最早到的一份，之后全部忽略
                duplicates += 1
                continue
            accepted += 1

            if span.parent_span_id:
                parent = self._get_span_row(span.trace_id, span.parent_span_id)
                if parent is not None:
                    # 父片段已在：直接产出一条调用边
                    self._record_edge(
                        parent,
                        callee_service=span.service,
                        start_ns=span.start_ns,
                        duration_ms=span.duration_ms,
                    )
                else:
                    # 父片段后到：先扣在一边等
                    self.orphans.add_waiting(
                        span.trace_id,
                        span.span_id,
                        span.parent_span_id,
                        arrival,
                        arrival + self._max_wait_ns,
                    )

        # 新片段可能正是某些等待中子片段的父片段：尝试归位
        resolved = self._reconcile(traces)
        timed_out = self._sweep_timeouts(arrival)
        return IngestResult(
            accepted=accepted,
            duplicates=duplicates,
            resolved_waits=resolved,
            timed_out=timed_out,
            affected_traces=sorted(traces),
        )

    def _get_span_row(self, trace_id: str, span_id: str):
        return self._db.conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? AND span_id = ?",
            (trace_id, span_id),
        ).fetchone()

    def _record_edge(self, parent_row, *, callee_service: str,
                     start_ns: int, duration_ms: float) -> None:
        """父片段服务 -> 子片段服务 记一条聚合边，按子片段开始时间落桶。"""
        bucket = (start_ns // EDGE_BUCKET_NS) * EDGE_BUCKET_NS
        self.dependencies.add_call(
            caller_service=parent_row["service"],
            callee_service=callee_service,
            bucket_ns=bucket,
            duration_ms=duration_ms,
        )

    def _reconcile(self, trace_ids: set[str]) -> int:
        """父片段已到达的 waiting 子片段立即归位（timeout 的不动），并补记调用边。"""
        resolved = 0
        for trace_id in trace_ids:
            # 只扫当前 trace 仍在 waiting 的记录
            rows = self._db.conn.execute(
                "SELECT span_id, parent_span_id FROM orphans "
                "WHERE trace_id = ? AND state = 'waiting'",
                (trace_id,),
            ).fetchall()
            for row in rows:
                parent = self._get_span_row(trace_id, row["parent_span_id"])
                if parent is None:
                    continue
                child = self._get_span_row(trace_id, row["span_id"])
                self.orphans.mark_resolved(trace_id, row["span_id"])
                # 子片段此刻才真正挂到父片段下：调用边也在归位时才记录
                if child is not None:
                    self._record_edge(
                        parent,
                        callee_service=child["service"],
                        start_ns=child["start_ns"],
                        duration_ms=child["duration_ms"],
                    )
                resolved += 1
        return resolved

    def _sweep_timeouts(self, now: int) -> int:
        """把超过最长等待时间仍没等到父片段的 waiting 记录置为 timeout。"""
        expired = self.orphans.list_expired_waiting(now)
        pairs = [(r["trace_id"], r["span_id"]) for r in expired]
        self.orphans.mark_timeout(pairs)
        return len(pairs)

    def sweep_timeouts(self, now: int | None = None) -> int:
        """供后台定时任务调用的公开入口。"""
        current = now if now is not None else now_ns()
        with self._db.lock:
            return self._sweep_timeouts(current)

    # ---------------------------------------------------------------- 读树
    def build_trace(self, trace_id: str) -> dict | None:
        """构建一棵完整调用树（含关键路径、服务耗时占比、占位节点）。"""
        rows = self.spans.list_by_trace(trace_id)
        if not rows:
            return None

        orphan_state = self.orphans.state_map(trace_id)
        known_ids = {r["span_id"] for r in rows}
        nodes: dict[str, dict] = {}

        for r in rows:
            parent_id = r["parent_span_id"]
            # 等父（waiting）或等父已超时（timeout）都先挂占位；
            # waiting 下即使父片段此刻已补到，也以 orphan 状态为准（未归位前不显示为已挂好）。
            # resolved 的孤儿按真实 parent 挂载。
            state = orphan_state.get(r["span_id"])
            if state in ("waiting", "timeout"):
                effective_parent = MISSING_PARENT_ID
            elif parent_id and parent_id not in known_ids:
                # 父编号指向压根不存在的片段：归占位，不影响整树拼接
                effective_parent = MISSING_PARENT_ID
            else:
                effective_parent = parent_id or None
            nodes[r["span_id"]] = {
                "span_id": r["span_id"],
                "parent_span_id": parent_id,
                "effective_parent_id": effective_parent,
                "service": r["service"],
                "start_time": ns_to_iso(r["start_ns"]),
                "end_time": ns_to_iso(r["end_ns"]),
                "start_ns": r["start_ns"],
                "end_ns": r["end_ns"],
                "duration_ms": r["duration_ms"],
                "status_code": r["status_code"],
                "is_error": r["status_code"] >= 500,
                "children": [],
            }
            if state == "waiting":
                nodes[r["span_id"]]["awaiting_parent"] = True
            elif state == "timeout":
                nodes[r["span_id"]]["parent_missing"] = True
            elif parent_id and parent_id not in known_ids:
                nodes[r["span_id"]]["parent_missing"] = True

        # 是否有片段需要挂占位节点
        under_placeholder = [
            n for n in nodes.values() if n["effective_parent_id"] == MISSING_PARENT_ID
        ]
        if under_placeholder:
            starts = [n["start_ns"] for n in under_placeholder]
            ends = [n["end_ns"] for n in under_placeholder]
            nodes[MISSING_PARENT_ID] = {
                "span_id": MISSING_PARENT_ID,
                "parent_span_id": None,
                "effective_parent_id": None,
                "service": MISSING_PARENT_SERVICE,
                "placeholder": True,
                "label": "父片段缺失（等待超时或父编号不存在）",
                "start_time": ns_to_iso(min(starts)),
                "end_time": ns_to_iso(max(ends)),
                "start_ns": min(starts),
                "end_ns": max(ends),
                "duration_ms": round((max(ends) - min(starts)) / 1_000_000, 3),
                "status_code": 0,
                "is_error": True,
                "children": [],
            }

        # 连边并找出根
        roots: list[dict] = []
        for node in nodes.values():
            parent_id = node["effective_parent_id"]
            if parent_id is None:
                roots.append(node)
            else:
                parent = nodes.get(parent_id)
                if parent is None:
                    # 理论上不会发生（占位节点已兜底），保险起见当根
                    node["effective_parent_id"] = None
                    roots.append(node)
                else:
                    parent["children"].append(node)

        # 占位节点尽量挂到唯一真实根下；多个真实根时独立成根
        placeholder = nodes.get(MISSING_PARENT_ID)
        real_roots = [n for n in roots if not n.get("placeholder")]
        if placeholder is not None and len(real_roots) == 1:
            roots.remove(placeholder)
            real_roots[0]["children"].append(placeholder)

        def sort_tree(node: dict) -> None:
            node["children"].sort(key=lambda n: (n["start_ns"], n["span_id"]))
            for child in node["children"]:
                sort_tree(child)

        for root in roots:
            sort_tree(root)

        # 关键路径：根到叶「片段自身耗时之和」最大的一条
        critical_ids: list[str] = []
        critical_total_ms = 0.0
        for root in roots:
            ids, total = _longest_path(root)
            if total > critical_total_ms:
                critical_ids, critical_total_ms = ids, total
        for node in nodes.values():
            node["on_critical_path"] = node["span_id"] in set(critical_ids)

        # 每个服务在这次请求里占的耗时比例（按片段自身耗时累加）
        service_ms: dict[str, float] = {}
        for node in nodes.values():
            if node.get("placeholder"):
                continue
            service_ms[node["service"]] = (
                service_ms.get(node["service"], 0.0) + node["duration_ms"]
            )
        total_ms = sum(service_ms.values()) or 1.0
        service_share = [
            {
                "service": service,
                "duration_ms": round(ms, 3),
                "share": round(ms / total_ms, 4),
            }
            for service, ms in sorted(service_ms.items(), key=lambda kv: -kv[1])
        ]

        return {
            "trace_id": trace_id,
            "roots": roots,
            "span_count": len([n for n in nodes.values() if not n.get("placeholder")]),
            "has_missing_parent": placeholder is not None,
            "critical_path": {
                "span_ids": critical_ids,
                "total_duration_ms": round(critical_total_ms, 3),
            },
            "service_share": service_share,
        }


def _longest_path(node: dict) -> tuple[list[str], float]:
    """返回从该节点出发到某叶子的最大耗时路径（节点 id 序列）及总耗时。"""
    if not node["children"]:
        return [node["span_id"]], node["duration_ms"]
    best_ids: list[str] = []
    best_total = -1.0
    for child in node["children"]:
        ids, total = _longest_path(child)
        if total > best_total:
            best_ids, best_total = ids, total
    return [node["span_id"], *best_ids], node["duration_ms"] + best_total
