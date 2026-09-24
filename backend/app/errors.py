"""领域错误类型：所有错误都带结构化 detail，便于前端直接展示。"""
from __future__ import annotations

from typing import Any


class TraceError(Exception):
    """业务错误基类，http_status 决定响应码，detail 为结构化错误说明。"""

    http_status: int = 400

    def __init__(self, detail: Any):
        super().__init__(str(detail))
        self.detail = detail


class SpanValidationError(TraceError):
    """片段校验失败：detail 为错误列表，每项含 index/field/message。"""

    http_status = 422


class NotFoundError(TraceError):
    http_status = 404


class BadRequestError(TraceError):
    http_status = 400
