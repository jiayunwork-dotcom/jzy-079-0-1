"""WebSocket 推送路由：把新片段上报、图更新等事件实时推给看板。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/events")
async def events_socket(websocket: WebSocket) -> None:
    hub = websocket.app.state.event_hub
    await websocket.accept()
    queue = await hub.register()

    async def wait_queue() -> tuple[str, str]:
        return ("event", await queue.get())

    async def wait_client() -> tuple[str, dict]:
        return ("client", await websocket.receive())

    try:
        # 连入先推一个 hello，便于前端确认连接
        await websocket.send_json({"type": "hello", "data": {"msg": "connected"}})
        while True:
            queue_task = asyncio.create_task(wait_queue())
            client_task = asyncio.create_task(wait_client())
            done, _pending = await asyncio.wait(
                {queue_task, client_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if client_task in done and queue_task not in done:
                queue_task.cancel()
                message = client_task.result()[1]
                if message.get("type") == "websocket.disconnect":
                    break
                # 客户端发来的其它内容一律忽略（看板是只读的）
                continue
            if queue_task in done and client_task not in done:
                client_task.cancel()
            elif queue_task not in done:
                # client_task 先完成且两边都完成的边角情况
                client_task.cancel()
                queue_task.cancel()
                break
            _, payload = queue_task.result()
            await websocket.send_text(payload)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await hub.unregister(queue)
