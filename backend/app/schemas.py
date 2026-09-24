"""上报片段的入参模型与边界校验。

校验全部在这里完成，脏数据绝不进入拼树流程：
- 追踪编号 / 片段编号 / 服务名不能为空
- 开始 / 结束时间必须可解析
- 结束时间不得早于开始时间

校验失败统一抛 SpanValidationError，detail 是结构化错误列表：
    [{"index": 3, "field": "end_time", "message": "..."}]
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .errors import SpanValidationError
from .timeutil import parse_timestamp_ns


class SpanIn(BaseModel):
    trace_id: str = Field(default="")
    span_id: str = Field(default="")
    parent_span_id: str | None = Field(default=None)
    service: str = Field(default="")
    start_time: Any = Field(default=None)
    end_time: Any = Field(default=None)
    status_code: int = Field(default=0)


class BatchIn(BaseModel):
    spans: list[SpanIn] = Field(default_factory=list)


class ValidatedSpan(BaseModel):
    """校验通过、时间已归一化为纳秒时间戳的片段。"""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    start_ns: int
    end_ns: int
    duration_ms: float
    status_code: int


def _add(errors: list[dict], index: int, field: str, message: str) -> None:
    errors.append({"index": index, "field": field, "message": message})


def validate_batch(payload: dict | list, max_batch_size: int) -> list[ValidatedSpan]:
    """校验整批上报，任何一片有问题则整批拒绝（不入库任何一片）。"""
    if isinstance(payload, list):
        raw_spans = payload
    elif isinstance(payload, dict) and isinstance(payload.get("spans"), list):
        raw_spans = payload["spans"]
    else:
        raise SpanValidationError(
            {
                "message": "请求体必须是片段数组，或含 spans 数组的对象",
                "errors": [],
            }
        )

    if len(raw_spans) == 0:
        raise SpanValidationError({"message": "上报批次为空", "errors": []})
    if len(raw_spans) > max_batch_size:
        raise SpanValidationError(
            {
                "message": f"单批片段数超过上限 {max_batch_size}",
                "errors": [],
            }
        )

    errors: list[dict] = []
    validated: list[ValidatedSpan] = []

    for index, raw in enumerate(raw_spans):
        try:
            item = SpanIn.model_validate(raw)
        except Exception as exc:  # pragma: no cover - pydantic 异常归一化
            _add(errors, index, "body", f"片段字段无法解析: {exc}")
            continue

        trace_id = (item.trace_id or "").strip()
        span_id = (item.span_id or "").strip()
        service = (item.service or "").strip()
        # 父编号空串视为根片段（等价于 null）
        parent_span_id = (
            item.parent_span_id.strip()
            if isinstance(item.parent_span_id, str) and item.parent_span_id.strip()
            else None
        )

        if not trace_id:
            _add(errors, index, "trace_id", "追踪编号不能为空")
        if not span_id:
            _add(errors, index, "span_id", "片段编号不能为空")
        if not service:
            _add(errors, index, "service", "服务名不能为空")

        try:
            start_ns = parse_timestamp_ns(item.start_time)
        except (ValueError, TypeError):
            _add(errors, index, "start_time", "缺少或无法解析开始时间")
            start_ns = None
        try:
            end_ns = parse_timestamp_ns(item.end_time)
        except (ValueError, TypeError):
            _add(errors, index, "end_time", "缺少或无法解析结束时间")
            end_ns = None

        if start_ns is not None and end_ns is not None and end_ns < start_ns:
            _add(errors, index, "end_time", "结束时间不能早于开始时间")

        has_error = any(e["index"] == index for e in errors)
        if not has_error:
            validated.append(
                ValidatedSpan(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    service=service,
                    start_ns=start_ns,
                    end_ns=end_ns,
                    duration_ms=round((end_ns - start_ns) / 1_000_000, 3),
                    status_code=item.status_code,
                )
            )

    if errors:
        raise SpanValidationError(
            {"message": f"{len(errors)} 个片段校验失败，整批已拒绝", "errors": errors}
        )
    return validated
