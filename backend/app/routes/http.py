"""HTTP 路由：片段上报、请求检索、调用树、依赖图。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..config import DEFAULT_WINDOW, DEPENDENCY_WINDOWS_SECONDS, MAX_BATCH_SIZE
from ..schemas import validate_batch

router = APIRouter(prefix="/api")


def _service(request: Request):
    return request.app.state.service


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int
    resolved_waits: int
    timed_out: int
    trace_ids: list[str]


@router.post("/spans", response_model=IngestResponse)
def report_spans(payload: dict[str, Any] | list[Any], request: Request) -> IngestResponse:
    """上报一批调用片段。任一片段非法则整批拒绝（422 + 结构化错误）。"""
    validated = validate_batch(payload, max_batch_size=MAX_BATCH_SIZE)
    result = _service(request).ingest_spans(validated)
    return IngestResponse(**result)


@router.get("/traces")
def search_traces(
    request: Request,
    trace_id: str | None = None,
    service: str | None = None,
    limit: int = 50,
):
    """请求检索列表：按追踪编号或服务名过滤。"""
    limit = max(1, min(limit, 200))
    return _service(request).search_traces(trace_id=trace_id, service=service, limit=limit)


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, request: Request):
    """单条请求的完整调用树（瀑布图数据）+ 关键路径 + 服务耗时占比。"""
    return _service(request).get_trace(trace_id)


@router.get("/dependencies")
def get_dependencies(request: Request, window: str = DEFAULT_WINDOW):
    """服务依赖图，window 支持配置的窗口档位（默认 1h），切换即按新窗口重算。"""
    return _service(request).get_dependency_graph(window)


@router.get("/windows")
def list_windows():
    return {
        "windows": [
            {"key": key, "seconds": seconds}
            for key, seconds in DEPENDENCY_WINDOWS_SECONDS.items()
        ],
        "default": DEFAULT_WINDOW,
    }


@router.get("/health")
def health():
    return {"status": "ok"}
