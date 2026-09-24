"""测试共用的片段构造辅助。"""
from __future__ import annotations

_NS = 1_000_000_000
# 固定基准时间：约 2026-09-24T00:00:00Z
BASE_NS = 1_790_000_000 * _NS


def span(
    trace_id="t1",
    span_id="s1",
    parent_span_id=None,
    service="gateway",
    start_ms: int = 0,
    duration_ms: int = 100,
    status_code: int = 200,
    start_time=None,
    end_time=None,
):
    """按毫秒偏移快速构造上报片段 dict。"""
    start_ns = BASE_NS + start_ms * 1_000_000
    end_ns = start_ns + duration_ms * 1_000_000
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "service": service,
        "start_time": start_time if start_time is not None else start_ns,
        "end_time": end_time if end_time is not None else end_ns,
        "status_code": status_code,
    }
