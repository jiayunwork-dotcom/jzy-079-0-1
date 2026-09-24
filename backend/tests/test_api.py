"""HTTP 端到端测试：验证路由层的结构化错误响应与完整上报/查询链路。"""
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
    app.state.db.close()


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_report_and_query_trace(client):
    payload = {
        "spans": [
            {"trace_id": "tr-1", "span_id": "root", "parent_span_id": None,
             "service": "gateway", "start_time": BASE_NS,
             "end_time": BASE_NS + 200_000_000, "status_code": 200},
            {"trace_id": "tr-1", "span_id": "child", "parent_span_id": "root",
             "service": "billing", "start_time": BASE_NS + 10_000_000,
             "end_time": BASE_NS + 150_000_000, "status_code": 500},
        ]
    }
    resp = client.post("/api/spans", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] == 2

    # 检索列表
    resp = client.get("/api/traces", params={"trace_id": "tr-1"})
    assert resp.status_code == 200
    traces = resp.json()
    assert len(traces) == 1
    assert traces[0]["trace_id"] == "tr-1"
    assert traces[0]["error_count"] == 1
    assert set(traces[0]["services"]) == {"gateway", "billing"}

    # 调用树
    resp = client.get("/api/traces/tr-1")
    assert resp.status_code == 200
    tree = resp.json()
    assert tree["span_count"] == 2
    root = tree["roots"][0]
    assert root["span_id"] == "root"
    assert root["children"][0]["span_id"] == "child"
    assert root["children"][0]["is_error"] is True
    assert tree["critical_path"]["span_ids"] == ["root", "child"]


def test_invalid_batch_returns_structured_422(client):
    payload = {"spans": [
        {"trace_id": "", "span_id": "a", "service": "s",
         "start_time": BASE_NS, "end_time": BASE_NS + 1},
    ]}
    resp = client.post("/api/spans", json=payload)
    assert resp.status_code == 422
    data = resp.json()["error"]
    assert "errors" in data
    assert data["errors"][0]["field"] == "trace_id"
    assert data["errors"][0]["index"] == 0

    # 脏数据未入库
    resp = client.get("/api/traces")
    assert resp.json() == []


def test_nonexistent_parent_via_http_does_not_fail(client):
    payload = {"spans": [
        {"trace_id": "tr-x", "span_id": "root", "parent_span_id": None,
         "service": "gateway", "start_time": BASE_NS,
         "end_time": BASE_NS + 100_000_000, "status_code": 200},
        {"trace_id": "tr-x", "span_id": "ghost-child",
         "parent_span_id": "nope", "service": "billing",
         "start_time": BASE_NS + 10_000_000,
         "end_time": BASE_NS + 50_000_000, "status_code": 200},
    ]}
    resp = client.post("/api/spans", json=payload)
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 2

    tree = client.get("/api/traces/tr-x").json()
    assert tree["has_missing_parent"] is True


def test_duplicate_report_via_http(client):
    span = {"trace_id": "tr-d", "span_id": "s", "parent_span_id": None,
            "service": "gateway", "start_time": BASE_NS,
            "end_time": BASE_NS + 100_000_000, "status_code": 200}
    r1 = client.post("/api/spans", json={"spans": [span]})
    r2 = client.post("/api/spans", json={"spans": [span]})
    assert r1.json()["accepted"] == 1
    assert r2.json()["accepted"] == 0
    assert r2.json()["duplicates"] == 1
    tree = client.get("/api/traces/tr-d").json()
    assert tree["span_count"] == 1


def test_dependency_window_endpoint(client):
    span = {"trace_id": "tr-g", "span_id": "s", "parent_span_id": None,
            "service": "gateway", "start_time": BASE_NS,
            "end_time": BASE_NS + 100_000_000, "status_code": 200}
    client.post("/api/spans", json={"spans": [span]})
    resp = client.get("/api/dependencies", params={"window": "24h"})
    assert resp.status_code == 200
    assert resp.json()["window"] == "24h"

    resp = client.get("/api/dependencies", params={"window": "bogus"})
    assert resp.status_code == 400


def test_missing_trace_404(client):
    resp = client.get("/api/traces/no-such-trace")
    assert resp.status_code == 404
