"""WebSocket 推送测试：新片段上报后，已连接的看板应实时收到事件。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

_NS = 1_000_000_000
BASE_NS = 1_790_000_000 * _NS


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def test_ws_receives_ingest_event(client):
    with client.websocket_connect("/ws/events") as ws:
        # hello
        hello = ws.receive_json()
        assert hello["type"] == "hello"

        # 上报一批片段
        resp = client.post("/api/spans", json={"spans": [
            {"trace_id": "ws-1", "span_id": "root", "parent_span_id": None,
             "service": "gateway", "start_time": BASE_NS,
             "end_time": BASE_NS + 100_000_000, "status_code": 200},
        ]})
        assert resp.status_code == 200

        # 客户端应收到 spans.ingested 与 graph.updated 两个事件
        types = []
        for _ in range(2):
            message = ws.receive_json()
            types.append(message["type"])
        assert "spans.ingested" in types
        assert "graph.updated" in types
