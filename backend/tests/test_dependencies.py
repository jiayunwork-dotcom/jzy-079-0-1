"""依赖图判据：
- 有环（A->B->A）时环上的边必须被标记 cyclic，正常 DAG 不能误标
- 切换时间窗口后边集合严格按新窗口重新聚合，旧窗口独有的边不出现
- 边上带调用次数与平均耗时
"""
from __future__ import annotations

from app.schemas import validate_batch

_NS = 1_000_000_000
BASE_NS = 1_790_000_000 * _NS

WINDOW_1H = 3600
WINDOW_24H = 86400


def ingest_at(service, spans, at_ns):
    validated = validate_batch({"spans": spans}, max_batch_size=100)
    return service.ingest_spans(validated, at_ns=at_ns)


def edge_map(graph) -> dict[tuple[str, str], dict]:
    return {(e["caller"], e["callee"]): e for e in graph["edges"]}


def test_dag_is_not_marked_cyclic(service):
    # gateway -> auth -> users，纯 DAG
    spans = [
        {"trace_id": "t1", "span_id": "g", "parent_span_id": None,
         "service": "gateway", "start_time": BASE_NS,
         "end_time": BASE_NS + 100_000_000, "status_code": 200},
        {"trace_id": "t1", "span_id": "a", "parent_span_id": "g",
         "service": "auth", "start_time": BASE_NS + 10_000_000,
         "end_time": BASE_NS + 90_000_000, "status_code": 200},
        {"trace_id": "t1", "span_id": "u", "parent_span_id": "a",
         "service": "users", "start_time": BASE_NS + 20_000_000,
         "end_time": BASE_NS + 60_000_000, "status_code": 200},
    ]
    ingest_at(service, spans, BASE_NS)
    graph = service.get_dependency_graph("1h", now=BASE_NS + 1000)
    assert graph["has_cycle"] is False
    assert graph["cyclic_edges"] == []
    assert all(e["cyclic"] is False for e in graph["edges"])
    assert set(edge_map(graph)) == {
        ("gateway", "auth"), ("auth", "users"),
    }


def test_cyclic_edges_marked(service):
    # A -> B -> A：通过两条不同的调用链构造环
    # trace1: A 调 B；trace2: B 调 A
    spans = [
        {"trace_id": "t1", "span_id": "a1", "parent_span_id": None,
         "service": "svc-a", "start_time": BASE_NS,
         "end_time": BASE_NS + 100_000_000, "status_code": 200},
        {"trace_id": "t1", "span_id": "b1", "parent_span_id": "a1",
         "service": "svc-b", "start_time": BASE_NS + 10_000_000,
         "end_time": BASE_NS + 50_000_000, "status_code": 200},
        {"trace_id": "t2", "span_id": "b2", "parent_span_id": None,
         "service": "svc-b", "start_time": BASE_NS + 1_000_000_000,
         "end_time": BASE_NS + 1_100_000_000, "status_code": 200},
        {"trace_id": "t2", "span_id": "a2", "parent_span_id": "b2",
         "service": "svc-a", "start_time": BASE_NS + 1_010_000_000,
         "end_time": BASE_NS + 1_050_000_000, "status_code": 200},
    ]
    ingest_at(service, spans, BASE_NS + 2_000_000_000)
    graph = service.get_dependency_graph("1h", now=BASE_NS + 2_000_000_000)
    assert graph["has_cycle"] is True
    edges = edge_map(graph)
    assert "svc-a->svc-b" in graph["cyclic_edges"]
    assert "svc-b->svc-a" in graph["cyclic_edges"]
    assert edges[("svc-a", "svc-b")]["cyclic"] is True
    assert edges[("svc-b", "svc-a")]["cyclic"] is True


def test_three_node_cycle_with_branch_only_marks_cycle_edges(service):
    # 环：A->B->C->A；外加一条环外分支 A->D，D 相关边不能被误标
    spans = []
    chain = [
        ("a", "svc-a", None), ("b", "svc-b", "a"),
        ("c", "svc-c", "b"), ("a-back", "svc-a", "c"),
        ("d", "svc-d", "a"),
    ]
    for i, (sid, svc, parent) in enumerate(chain):
        spans.append({
            "trace_id": "t1", "span_id": sid, "parent_span_id": parent,
            "service": svc,
            "start_time": BASE_NS + i * 10_000_000,
            "end_time": BASE_NS + i * 10_000_000 + 5_000_000,
            "status_code": 200,
        })
    ingest_at(service, spans, BASE_NS)
    graph = service.get_dependency_graph("1h", now=BASE_NS + 1000)
    edges = edge_map(graph)
    cyclic = set(graph["cyclic_edges"])
    assert cyclic == {
        "svc-a->svc-b", "svc-b->svc-c", "svc-c->svc-a",
    }
    assert edges[("svc-a", "svc-d")]["cyclic"] is False


def test_self_loop_marked(service):
    spans = [
        {"trace_id": "t1", "span_id": "x1", "parent_span_id": None,
         "service": "svc-x", "start_time": BASE_NS,
         "end_time": BASE_NS + 100_000_000, "status_code": 200},
        {"trace_id": "t1", "span_id": "x2", "parent_span_id": "x1",
         "service": "svc-x", "start_time": BASE_NS + 10_000_000,
         "end_time": BASE_NS + 50_000_000, "status_code": 200},
    ]
    ingest_at(service, spans, BASE_NS)
    graph = service.get_dependency_graph("1h", now=BASE_NS + 1000)
    assert graph["has_cycle"] is True
    assert graph["cyclic_edges"] == ["svc-x->svc-x"]


def test_window_switch_excludes_old_edges(service):
    # 旧调用（3 小时前）：gateway -> legacy
    old_spans = [
        {"trace_id": "old1", "span_id": "g", "parent_span_id": None,
         "service": "gateway", "start_time": BASE_NS - 3 * 3600 * _NS,
         "end_time": BASE_NS - 3 * 3600 * _NS + 100_000_000, "status_code": 200},
        {"trace_id": "old1", "span_id": "l", "parent_span_id": "g",
         "service": "legacy", "start_time": BASE_NS - 3 * 3600 * _NS + 10_000_000,
         "end_time": BASE_NS - 3 * 3600 * _NS + 50_000_000, "status_code": 200},
    ]
    # 新调用（最近一小时内）：gateway -> modern
    new_spans = [
        {"trace_id": "new1", "span_id": "g", "parent_span_id": None,
         "service": "gateway", "start_time": BASE_NS,
         "end_time": BASE_NS + 100_000_000, "status_code": 200},
        {"trace_id": "new1", "span_id": "m", "parent_span_id": "g",
         "service": "modern", "start_time": BASE_NS + 10_000_000,
         "end_time": BASE_NS + 80_000_000, "status_code": 200},
    ]
    ingest_at(service, old_spans + new_spans, BASE_NS)
    now = BASE_NS

    # 最近一小时：只有新边，旧窗口独有边 legacy 不得出现
    g1h = service.get_dependency_graph("1h", now=now)
    assert set(edge_map(g1h)) == {("gateway", "modern")}

    # 切到最近一天：新老边都在（全量重算，不与 1h 结果互相污染）
    g24h = service.get_dependency_graph("24h", now=now)
    assert set(edge_map(g24h)) == {
        ("gateway", "modern"), ("gateway", "legacy"),
    }

    # 再切回 1h：仍然只有新边，验证不是缓存串窗
    g1h_again = service.get_dependency_graph("1h", now=now)
    assert set(edge_map(g1h_again)) == {("gateway", "modern")}


def test_edge_count_and_average_duration(service):
    # gateway -> auth 调用两次，分别耗时 40ms 和 80ms
    spans = []
    for trace_id, dur_ms in (("t1", 40), ("t2", 80)):
        start = BASE_NS
        spans.append({
            "trace_id": trace_id, "span_id": "g", "parent_span_id": None,
            "service": "gateway", "start_time": start,
            "end_time": start + 200_000_000, "status_code": 200,
        })
        spans.append({
            "trace_id": trace_id, "span_id": "a", "parent_span_id": "g",
            "service": "auth",
            "start_time": start + 10_000_000,
            "end_time": start + 10_000_000 + dur_ms * 1_000_000,
            "status_code": 200,
        })
    ingest_at(service, spans, BASE_NS)
    graph = service.get_dependency_graph("1h", now=BASE_NS + 1000)
    edge = edge_map(graph)[("gateway", "auth")]
    assert edge["count"] == 2
    assert edge["avg_duration_ms"] == 60.0


def test_node_size_reflects_call_frequency(service):
    spans = [
        # gateway 发起 3 次调用，users 发起 0 次
        *_root_and_child("t1", "gateway", "auth", BASE_NS),
        *_root_and_child("t2", "gateway", "users", BASE_NS + 10_000_000),
        *_root_and_child("t3", "gateway", "users", BASE_NS + 20_000_000),
    ]
    ingest_at(service, spans, BASE_NS)
    graph = service.get_dependency_graph("1h", now=BASE_NS + 1000)
    nodes = {n["service"]: n for n in graph["nodes"]}
    assert nodes["gateway"]["call_count"] == 3
    assert nodes["users"]["called_count"] == 2
    assert nodes["auth"]["called_count"] == 1


def _root_and_child(trace_id, root_svc, child_svc, start_ns):
    return [
        {"trace_id": trace_id, "span_id": "g", "parent_span_id": None,
         "service": root_svc, "start_time": start_ns,
         "end_time": start_ns + 100_000_000, "status_code": 200},
        {"trace_id": trace_id, "span_id": "c", "parent_span_id": "g",
         "service": child_svc, "start_time": start_ns + 10_000_000,
         "end_time": start_ns + 50_000_000, "status_code": 200},
    ]


def test_waiting_and_timed_out_orphan_produces_no_edge(service):
    """父片段尚未到达 / 最终超时归占位时，都不能产出调用边。"""
    # 先到子片段，父缺失
    child = {
        "trace_id": "t-wait", "span_id": "c", "parent_span_id": "ghost",
        "service": "billing", "start_time": BASE_NS,
        "end_time": BASE_NS + 50_000_000, "status_code": 200,
    }
    ingest_at(service, [child], BASE_NS)
    g = service.get_dependency_graph("1h", now=BASE_NS + 1000)
    assert g["edges"] == []

    # 等待超时归占位后仍然没有边（不能出现 caller=unknown 的脏边）
    service.sweep_timeouts(BASE_NS + 60 * 1_000_000_000)
    g = service.get_dependency_graph("1h", now=BASE_NS + 60 * 1_000_000_000)
    assert g["edges"] == []


def test_edge_recorded_when_late_parent_resolves(service):
    """父片段延迟到达、子片段归位后，调用边才出现在图里（且只出现一次）。"""
    child = {
        "trace_id": "t-late", "span_id": "c", "parent_span_id": "p",
        "service": "billing", "start_time": BASE_NS,
        "end_time": BASE_NS + 50_000_000, "status_code": 200,
    }
    ingest_at(service, [child], BASE_NS)
    assert service.get_dependency_graph("1h", now=BASE_NS + 1000)["edges"] == []

    parent = {
        "trace_id": "t-late", "span_id": "p", "parent_span_id": None,
        "service": "gateway", "start_time": BASE_NS - 5_000_000,
        "end_time": BASE_NS + 60_000_000, "status_code": 200,
    }
    ingest_at(service, [parent], BASE_NS + 100_000)
    g = service.get_dependency_graph("1h", now=BASE_NS + 200_000)
    edges = edge_map(g)
    assert set(edges) == {("gateway", "billing")}
    assert edges[("gateway", "billing")]["count"] == 1
