"""服务依赖图：按时间窗口聚合调用边 + 环检测。

- 边方向：caller -> callee（父片段服务调用子片段服务）
- 每次窗口查询都严格按「当前时刻 - 窗口长度」重新从 span 事实聚合，
  窗口切换是全量重算，新旧窗口的边绝不混在一起。
- 环检测：Tarjan 强连通分量，节点数 > 1 的 SCC 内所有边（含自调用）
  标记为 cyclic，前端高亮这些边。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from .repositories.db import EDGE_BUCKET_NS, Database
from .repositories.dependencies import DependencyRepository
from .timeutil import NS_PER_SECOND, now_ns


@dataclass(frozen=True)
class Edge:
    caller: str
    callee: str
    count: int
    avg_duration_ms: float
    cyclic: bool = False


def _tarjan_cyclic_edges(nodes: set[str], edges: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """返回落在强连通分量内部的边集合（这些边参与了环）。"""
    sys.setrecursionlimit(max(10000, len(nodes) * 4 + 1000))
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for caller, callee in edges:
        adj.setdefault(caller, []).append(callee)
        adj.setdefault(callee, [])

    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        indices[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj[v]:
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], indices[w])
        if lowlink[v] == indices[v]:
            component = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            sccs.append(component)

    for node in list(adj.keys()):
        if node not in indices:
            strongconnect(node)

    cyclic_nodes: set[str] = set()
    for component in sccs:
        if len(component) > 1:
            cyclic_nodes.update(component)

    cyclic_edges: set[tuple[str, str]] = set()
    edge_set = set(edges)
    for caller, callee in edges:
        if caller == callee and (caller, callee) in edge_set:
            # 自调用天然成环
            cyclic_edges.add((caller, callee))
        elif caller in cyclic_nodes and callee in cyclic_nodes:
            cyclic_edges.add((caller, callee))
    return cyclic_edges


class DependencyGraphBuilder:
    def __init__(self, db: Database):
        self.edges_repo = DependencyRepository(db)

    def build(self, window_seconds: int, now: int | None = None) -> dict:
        """按最近 window_seconds 秒内的聚合边全量重算依赖图。

        边只在片段真正挂到父片段下时写入 dep_edges，
        等父超时（最终挂占位）的片段不会产生调用边。
        """
        current = now if now is not None else now_ns()
        since_ns = current - int(window_seconds * NS_PER_SECOND)
        # 桶下界向上对齐到「起点不早于窗口起点的第一个桶」，
        # 保证结果里的每条边都严格对应窗口内发生的调用，不混进窗外半桶
        since_bucket = ((since_ns + EDGE_BUCKET_NS - 1) // EDGE_BUCKET_NS) * EDGE_BUCKET_NS

        nodes: set[str] = set()
        raw_edges: list[tuple[str, str]] = []
        edges: list[Edge] = []
        for row in self.edges_repo.aggregate_since(since_bucket):
            caller, callee = row["caller"], row["callee"]
            count = int(row["count"])
            total_ms = float(row["total_duration_ms"])
            nodes.add(caller)
            nodes.add(callee)
            raw_edges.append((caller, callee))
            edges.append(
                Edge(
                    caller=caller,
                    callee=callee,
                    count=count,
                    avg_duration_ms=round(total_ms / count, 3),
                )
            )

        cyclic_edges = _tarjan_cyclic_edges(nodes, raw_edges)
        out_edges: list[dict] = []
        for edge in edges:
            is_cyclic = (edge.caller, edge.callee) in cyclic_edges
            out_edges.append(
                {
                    "caller": edge.caller,
                    "callee": edge.callee,
                    "count": edge.count,
                    "avg_duration_ms": edge.avg_duration_ms,
                    "cyclic": is_cyclic,
                }
            )

        # 节点大小按「作为调用方发起的调用次数」区分，同时给出总频次
        outgoing_count: dict[str, int] = {n: 0 for n in nodes}
        incoming_count: dict[str, int] = {n: 0 for n in nodes}
        for edge in out_edges:
            outgoing_count[edge["caller"]] += edge["count"]
            incoming_count[edge["callee"]] += edge["count"]
        out_nodes = [
            {
                "service": name,
                "call_count": outgoing_count[name],
                "called_count": incoming_count[name],
                "total_calls": outgoing_count[name] + incoming_count[name],
            }
            for name in sorted(nodes)
        ]

        cyclic_edge_ids = [
            f"{e['caller']}->{e['callee']}" for e in out_edges if e["cyclic"]
        ]
        return {
            "window_seconds": window_seconds,
            "nodes": out_nodes,
            "edges": sorted(out_edges, key=lambda e: (e["caller"], e["callee"])),
            "has_cycle": bool(cyclic_edge_ids),
            "cyclic_edges": cyclic_edge_ids,
            "computed_at_ns": current,
        }
