"""实时推送枢纽：后端线程（同步 SQLite 写入）把事件丢给事件循环广播给所有 WebSocket。

ingest 在 FastAPI 的线程池里执行（同步代码），因此用
asyncio.run_coroutine_threadsafe 跨线程投递事件。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger("traceboard.events")


class EventHub:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """应用启动时记录主事件循环。"""
        self._loop = loop

    async def register(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._clients.add(queue)
        logger.info("ws client connected, total=%d", len(self._clients))
        return queue

    async def unregister(self, queue: asyncio.Queue) -> None:
        self._clients.discard(queue)
        logger.info("ws client disconnected, total=%d", len(self._clients))

    async def _broadcast(self, message: dict[str, Any]) -> None:
        payload = json.dumps(message, ensure_ascii=False, default=str)
        dead: list[asyncio.Queue] = []
        for queue in self._clients:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self._clients.discard(queue)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        """线程安全的事件发布入口（供同步业务代码调用）。"""
        if self._loop is None or not self._clients:
            return
        message = {"type": event_type, "data": data}
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self._loop)
        except RuntimeError:
            pass  # 事件循环已关闭
