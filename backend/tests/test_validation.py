"""非法片段拒绝判据：
- 缺开始/结束时间、结束早于开始、trace_id/span_id 为空都必须拒绝
- 错误是结构化的（含 index/field/message），且整批拒绝、不入库
"""
from __future__ import annotations

import pytest

from app.errors import SpanValidationError
from app.schemas import validate_batch

from tests.helpers import span


def test_missing_start_time_rejected():
    payload = {"spans": [{
        "trace_id": "t", "span_id": "a", "service": "svc",
        "start_time": None, "end_time": 1_790_000_001_000_000_000,
    }]}
    with pytest.raises(SpanValidationError) as exc:
        validate_batch(payload, max_batch_size=100)
    err = exc.value.detail
    fields = {(e["index"], e["field"]) for e in err["errors"]}
    assert (0, "start_time") in fields


def test_missing_end_time_rejected():
    payload = [{"span_id": "a", "trace_id": "t", "service": "svc",
                "start_time": 1_790_000_000_000_000_000}]
    with pytest.raises(SpanValidationError) as exc:
        validate_batch(payload, max_batch_size=100)
    assert any(e["field"] == "end_time" for e in exc.value.detail["errors"])


def test_end_before_start_rejected():
    payload = [{"span_id": "a", "trace_id": "t", "service": "svc",
                "start_time": 2_000_000_000, "end_time": 1_000_000_000}]
    with pytest.raises(SpanValidationError) as exc:
        validate_batch(payload, max_batch_size=100)
    assert any(e["field"] == "end_time" and "早于" in e["message"]
               for e in exc.value.detail["errors"])


def test_empty_trace_or_span_id_rejected():
    payload = [
        {"trace_id": "", "span_id": "a", "service": "svc",
         "start_time": 1, "end_time": 2},
        {"trace_id": "t", "span_id": "  ", "service": "svc",
         "start_time": 1, "end_time": 2},
    ]
    with pytest.raises(SpanValidationError) as exc:
        validate_batch(payload, max_batch_size=100)
    fields = {e["field"] for e in exc.value.detail["errors"]}
    assert "trace_id" in fields
    assert "span_id" in fields


def test_unparsable_timestamp_and_naive_iso_rejected():
    payload = [{"trace_id": "t", "span_id": "a", "service": "svc",
                "start_time": "not-a-time",
                "end_time": "2026-09-24T10:00:00"}]  # 无时区
    with pytest.raises(SpanValidationError) as exc:
        validate_batch(payload, max_batch_size=100)
    bad_fields = {e["field"] for e in exc.value.detail["errors"]}
    assert "start_time" in bad_fields
    assert "end_time" in bad_fields


def test_one_bad_span_rejects_whole_batch(service):
    """整批拒绝：脏数据存在时，同批的合法片段也不能入树。"""
    good = span(span_id="good")
    bad = span(span_id="", start_ms=10)
    with pytest.raises(SpanValidationError):
        # 走 service 前置的校验函数
        from app.schemas import validate_batch
        validate_batch({"spans": [good, bad]}, max_batch_size=100)
    # 确认库里没有这条 trace
    assert service.assembler.spans.trace_exists("t1") is False


def test_empty_batch_rejected():
    with pytest.raises(SpanValidationError):
        validate_batch({"spans": []}, max_batch_size=100)


def test_valid_iso_with_z_accepted():
    payload = [{
        "trace_id": "t", "span_id": "a", "service": "svc",
        "start_time": "2026-09-24T00:00:00Z",
        "end_time": "2026-09-24T00:00:00.100+00:00",
    }]
    validated = validate_batch(payload, max_batch_size=100)
    assert len(validated) == 1
    assert validated[0].duration_ms == 100.0
