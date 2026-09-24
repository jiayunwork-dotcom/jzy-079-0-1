"""FastAPI 应用装配：生命周期、结构化错误处理、后台孤儿超时扫描。"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import DB_PATH, GRAPH_REFRESH_INTERVAL_SECONDS
from .errors import TraceError
from .events import EventHub
from .repositories.db import Database
from .routes import http as http_routes
from .routes import websocket as ws_routes
from .service import TraceService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("traceboard")


def create_app(db_path: str = DB_PATH) -> FastAPI:
    async def _orphan_sweeper(application: FastAPI) -> None:
        """周期性把等父超时的片段归入占位节点。"""
        while True:
            await asyncio.sleep(GRAPH_REFRESH_INTERVAL_SECONDS)
            try:
                n = application.state.service.sweep_timeouts()
                if n:
                    logger.info("orphan spans timed out: %d", n)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("orphan sweeper failed")

    @contextlib.asynccontextmanager
    async def lifespan(application: FastAPI):
        db = Database(db_path)
        event_hub = EventHub()
        event_hub.bind_loop(asyncio.get_running_loop())
        application.state.db = db
        application.state.event_hub = event_hub
        application.state.service = TraceService(db, event_hub=event_hub)
        sweeper_task = asyncio.create_task(_orphan_sweeper(application))
        try:
            yield
        finally:
            sweeper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper_task
            db.close()

    app = FastAPI(title="分布式链路追踪看板", version="1.0.0", lifespan=lifespan)

    # 开发态前端 (vite :5173) 与同源 nginx 都能访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(TraceError)
    async def trace_error_handler(request: Request, exc: TraceError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content={"error": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 请求体本身不是合法 JSON / 结构不对时，也归一化成结构化错误
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "message": "请求结构不合法",
                    "errors": [
                        {"index": None, "field": ".".join(str(p) for p in e["loc"][1:]),
                         "message": e["msg"]}
                        for e in exc.errors()
                    ],
                }
            },
        )

    app.include_router(http_routes.router)
    app.include_router(ws_routes.router)
    return app


app = create_app()
