"""调用树拼接判据：
1) 父片段延后到达：子先等待，父到后正确归位；未超时不得提前归占位
2) 超时后才归占位节点
3) 重复上报只保留一份
4) 父编号指向不存在的片段：不报错，其它片段正常入树，子归占位
5) 上报顺序打乱，最终树结构一致
"""
from __future__ import annotations

from app.assembler import MISSING_PARENT_ID
from app.schemas import validate_batch

from tests.helpers import BASE_NS, span

_NS = 1_000_000_000

WAIT_NS = int(1.0 * 1_000_000_000)  # 与 conftest 的最大等待一致


def ingest(service, spans, at_ns):
    validated = validate_batch({"spans": spans}, max_batch_size=100)
    return service.ingest_spans(validated, at_ns=at_ns)


def index_nodes(tree) -> dict:
    """把树拍平成 span_id -> node 映射。"""
    out = {}

    def walk(node):
        out[node["span_id"]] = node
        for child in node["children"]:
            walk(child)

    for root in tree["roots"]:
        walk(root)
    return out


# ---------------------------------------------------------------- 父片段延后
def test_late_parent_child_waits_then_attaches(service):
    child = span(span_id="child", parent_span_id="root", service="billing",
                 start_ms=20, duration_ms=50)

    # 第一批：只有子片段，父还没到
    result = ingest(service, [child], at_ns=BASE_NS)
    assert result["accepted"] == 1
    tree = service.get_trace("t1")
    nodes = index_nodes(tree)
    # 父未到且未超时：子片段应处于「等待父片段」状态（挂占位下并标注 awaiting）
    assert nodes["child"]["awaiting_parent"] is True
    assert nodes["child"]["effective_parent_id"] == MISSING_PARENT_ID
    assert MISSING_PARENT_ID in nodes

    # 第二批：父片段在超时前到达 -> 子片段归位到真实父片段下
    root = span(span_id="root", service="gateway", start_ms=0, duration_ms=100)
    result = ingest(service, [root], at_ns=BASE_NS + WAIT_NS // 2)
    assert result["resolved_waits"] == 1
    tree = service.get_trace("t1")
    nodes = index_nodes(tree)
    assert nodes["child"]["effective_parent_id"] == "root"
    assert [c["span_id"] for c in nodes["root"]["children"]] == ["child"]
    # 已全部归位，占位节点不应再出现
    assert MISSING_PARENT_ID not in nodes
    assert tree["has_missing_parent"] is False


def test_child_times_out_to_placeholder_only_after_limit(service):
    child = span(span_id="child", parent_span_id="root", start_ms=10)
    ingest(service, [child], at_ns=BASE_NS)

    # 还没到超时点，不能提前归到占位（状态仍是等待，树里也不作为已缺失定论）
    service.sweep_timeouts(BASE_NS + WAIT_NS - 1)
    tree = service.get_trace("t1")
    nodes = index_nodes(tree)
    assert nodes["child"]["awaiting_parent"] is True
    assert nodes["child"].get("parent_missing") is None

    # 超过最长等待仍没等到父片段 -> 归入占位节点，且不可逆
    n = service.sweep_timeouts(BASE_NS + WAIT_NS + 1)
    assert n == 1
    tree = service.get_trace("t1")
    nodes = index_nodes(tree)
    assert nodes["child"]["parent_missing"] is True
    assert nodes[MISSING_PARENT_ID]["placeholder"] is True
    assert [c["span_id"] for c in nodes[MISSING_PARENT_ID]["children"]] == ["child"]

    # 超时之后父片段才补到：不再改挂（timeout 不可逆）
    root = span(span_id="root", start_ms=0, duration_ms=100)
    result = ingest(service, [root], at_ns=BASE_NS + WAIT_NS + 10)
    assert result["resolved_waits"] == 0
    tree = service.get_trace("t1")
    nodes = index_nodes(tree)
    assert nodes["child"]["effective_parent_id"] == MISSING_PARENT_ID


# ---------------------------------------------------------------- 重复上报
def test_duplicate_span_report_ignored(service):
    first = span(span_id="dup", service="gateway", start_ms=0, duration_ms=100)
    # 第二份重复上报，改了 service 和耗时，必须被忽略
    second = span(span_id="dup", service="EVIL-SERVICE", start_ms=0, duration_ms=999)

    r1 = ingest(service, [first], at_ns=BASE_NS)
    r2 = ingest(service, [second], at_ns=BASE_NS + 100)
    assert r1["accepted"] == 1
    assert r2["accepted"] == 0
    assert r2["duplicates"] == 1

    tree = service.get_trace("t1")
    nodes = index_nodes(tree)
    assert tree["span_count"] == 1
    node = nodes["dup"]
    assert node["service"] == "gateway"
    assert node["duration_ms"] == 100.0


def test_duplicate_span_same_batch_ignored(service):
    s = span(span_id="dup")
    result = ingest(service, [s, dict(s)], at_ns=BASE_NS)
    assert result["accepted"] == 1
    assert result["duplicates"] == 1
    assert service.get_trace("t1")["span_count"] == 1


# ---------------------------------------------------------------- 父编号不存在
def test_nonexistent_parent_does_not_break_tree(service):
    root = span(span_id="root", start_ms=0, duration_ms=200)
    good_child = span(span_id="child-a", parent_span_id="root", service="auth",
                      start_ms=10, duration_ms=50)
    orphan = span(span_id="child-b", parent_span_id="does-not-exist",
                  service="billing", start_ms=60, duration_ms=50)

    result = ingest(service, [root, good_child, orphan], at_ns=BASE_NS)
    # 整批不报错，3 片全部入库
    assert result["accepted"] == 3
    tree = service.get_trace("t1")
    nodes = index_nodes(tree)
    assert tree["span_count"] == 3

    # 正常片段照常挂树
    assert nodes["root"].get("placeholder") is not True
    assert "child-a" in {c["span_id"] for c in nodes["root"]["children"]}
    # 指向不存在父编号的片段：拼接不失败，已挂到占位节点下（等待期标 awaiting）
    assert nodes["child-b"]["effective_parent_id"] == MISSING_PARENT_ID
    assert nodes["child-b"]["awaiting_parent"] is True
    # 占位挂在唯一真实根下面
    assert MISSING_PARENT_ID in {c["span_id"] for c in nodes["root"]["children"]}

    # 超过最长等待，父编号依然不存在 -> 永久标记 parent_missing
    service.sweep_timeouts(BASE_NS + WAIT_NS + 1)
    nodes = index_nodes(service.get_trace("t1"))
    assert nodes["child-b"]["parent_missing"] is True
    assert nodes["child-b"].get("awaiting_parent") is None


# ---------------------------------------------------------------- 顺序无关
def _make_three_level_spans():
    return [
        span(span_id="a", service="a-svc", start_ms=0, duration_ms=300),
        span(span_id="b", parent_span_id="a", service="b-svc",
             start_ms=10, duration_ms=200),
        span(span_id="c", parent_span_id="b", service="c-svc",
             start_ms=20, duration_ms=100),
        span(span_id="d", parent_span_id="a", service="d-svc",
             start_ms=30, duration_ms=40),
    ]


def test_tree_structure_independent_of_report_order(service):
    import itertools

    reference = None
    for order in itertools.permutations(_make_three_level_spans()):
        # 每种顺序用一个全新 service（全新内存库）
        from app.assembler import TreeAssembler
        from app.events import EventHub
        from app.repositories.db import Database

        db = Database(":memory:")
        svc = service.__class__(db, event_hub=EventHub())
        svc.assembler = TreeAssembler(db, max_wait_seconds=1.0)
        ingest(svc, list(order), at_ns=BASE_NS)
        tree = svc.get_trace("t1")
        # 只比对结构（父子关系），忽略时间展示字段
        structure = {
            nid: [c["span_id"] for c in n["children"]]
            for nid, n in index_nodes(tree).items()
        }
        if reference is None:
            reference = structure
        else:
            assert structure == reference

    # 最终断言结构内容
    assert reference["a"] == ["b", "d"]
    assert reference["b"] == ["c"]
    assert reference["c"] == []


def test_critical_path_and_service_share(service):
    spans = [
        span(span_id="a", service="gateway", start_ms=0, duration_ms=100),
        span(span_id="slow", parent_span_id="a", service="slow-svc",
             start_ms=10, duration_ms=80),
        span(span_id="fast", parent_span_id="a", service="fast-svc",
             start_ms=10, duration_ms=10),
    ]
    ingest(service, spans, at_ns=BASE_NS)
    tree = service.get_trace("t1")
    # a(100) -> slow(80) 是最长根叶路径
    assert tree["critical_path"]["span_ids"] == ["a", "slow"]
    assert tree["critical_path"]["total_duration_ms"] == 180.0

    shares = {item["service"]: item for item in tree["service_share"]}
    assert shares["slow-svc"]["share"] > shares["fast-svc"]["share"]
