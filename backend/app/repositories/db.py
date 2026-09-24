"""SQLite 持久化。

三张表：
- spans       : 片段本体（按 trace_id+span_id 去重，只留最早到的那份）
- orphans     : 等父片段的记录及状态（waiting -> resolved / timeout）
- dep_edges   : 按「子服务->父服务 + 1 秒时间桶」预聚合的调用边，
                依赖图按时间窗口从这里重新聚合，不混窗口。

单进程后端 + 一把锁串行化写入即可；WAL 模式保证读请求不被写阻塞。
"""
from __future__ import annotations

import os
import sqlite3
import threading


SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    trace_id       TEXT NOT NULL,
    span_id        TEXT NOT NULL,
    parent_span_id TEXT,
    service        TEXT NOT NULL,
    start_ns       INTEGER NOT NULL,
    end_ns         INTEGER NOT NULL,
    duration_ms    REAL NOT NULL,
    status_code    INTEGER NOT NULL,
    arrival_ns     INTEGER NOT NULL,
    PRIMARY KEY (trace_id, span_id)
);

CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans (trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_service ON spans (service);
CREATE INDEX IF NOT EXISTS idx_spans_start ON spans (start_ns);

CREATE TABLE IF NOT EXISTS orphans (
    trace_id       TEXT NOT NULL,
    span_id        TEXT NOT NULL,
    parent_span_id TEXT NOT NULL,
    state          TEXT NOT NULL CHECK (state IN ('waiting', 'resolved', 'timeout')),
    since_ns       INTEGER NOT NULL,
    timeout_ns     INTEGER NOT NULL,
    PRIMARY KEY (trace_id, span_id)
);

CREATE INDEX IF NOT EXISTS idx_orphans_waiting ON orphans (state, timeout_ns);

CREATE TABLE IF NOT EXISTS dep_edges (
    caller_service  TEXT NOT NULL,
    callee_service  TEXT NOT NULL,
    bucket_ns       INTEGER NOT NULL,
    count           INTEGER NOT NULL,
    total_duration_ms REAL NOT NULL,
    PRIMARY KEY (caller_service, callee_service, bucket_ns)
);

CREATE INDEX IF NOT EXISTS idx_dep_bucket ON dep_edges (bucket_ns);
"""

# 依赖边时间桶大小：1 秒（纳秒）
EDGE_BUCKET_NS = 1_000_000_000


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.executescript(SCHEMA)

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        with self._lock:
            self._conn.close()
