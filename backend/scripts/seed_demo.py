"""生成一组演示调用片段并上报，覆盖：
- 正常多级调用树 + 失败片段（500）
- 父片段延迟到达（子先上报，5 秒后父才到）
- 父编号指向不存在片段（等父超时后归占位）
- 服务间循环依赖（svc-a -> svc-b -> svc-a）

用法（后端启动后）：
    python scripts/seed_demo.py [base_url]
默认 base_url 为 http://localhost:8000
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
NS = 1_000_000_000
now_ns = time.time_ns()


def post_spans(spans: list[dict]) -> dict:
    req = urllib.request.Request(
        f"{BASE}/api/spans",
        data=json.dumps({"spans": spans}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def span(trace_id, span_id, parent, service, start_ms, dur_ms, status=200):
    start = now_ns + start_ms * 1_000_000
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent,
        "service": service,
        "start_time": start,
        "end_time": start + dur_ms * 1_000_000,
        "status_code": status,
    }


def main() -> None:
    # 1) 一棵正常的 4 层调用树，billing 失败
    t1 = "demo-trace-正常链路"
    tree1 = [
        span(t1, "root", None, "gateway", 0, 320),
        span(t1, "auth", "root", "auth", 8, 60),
        span(t1, "orders", "root", "orders", 15, 280),
        span(t1, "users", "auth", "users", 12, 40),
        span(t1, "billing", "orders", "billing", 40, 150, status=500),
        span(t1, "inventory", "orders", "inventory", 30, 90),
        span(t1, "warehouse", "inventory", "warehouse", 20, 50),
    ]

    # 2) 循环依赖的两半：A 调 B
    t2 = "demo-trace-环-A调B"
    cyc1 = [
        span(t2, "a1", None, "svc-a", 0, 120),
        span(t2, "b1", "a1", "svc-b", 10, 80),
    ]
    # B 又绕回调 A
    t3 = "demo-trace-环-B调A"
    cyc2 = [
        span(t3, "b2", None, "svc-b", 0, 110),
        span(t3, "a2", "b2", "svc-a", 10, 70),
    ]

    # 3) 父编号压根不存在：上报后需等到超时（ORPHAN_MAX_WAIT_SECONDS）才归占位
    t4 = "demo-trace-缺失父片段"
    ghost = [span(t4, "lonely", "never-arrived", "reports", 0, 45)]

    # 4) 父片段晚到：先只报子片段，5 秒后再报父片段，子应自动归位
    t5 = "demo-trace-父延迟到达"
    early_child = [span(t5, "child", "late-root", "notify", 100, 80)]

    batches = [tree1, cyc1, cyc2, ghost, early_child]
    for batch in batches:
        result = post_spans(batch)
        print(f"上报 {len(batch)} 片 -> {result}")

    print("等待 1 秒后补发迟到的父片段 late-root …")
    time.sleep(1)
    late = [span(t5, "late-root", None, "gateway", 0, 220)]
    print(f"补发 -> {post_spans(late)}")
    print(
        "\n演示数据上报完成：\n"
        f"  - 打开看板检索 {t1}\n"
        "  - 依赖图页可看到 svc-a <-> svc-b 的红色环\n"
        f"  - {t4} 的 lonely 片段会在等待超时后归入占位节点"
    )


if __name__ == "__main__":
    main()
