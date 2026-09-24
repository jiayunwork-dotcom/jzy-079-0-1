"""片段（span）表的数据访问。"""
from __future__ import annotations

import sqlite3

from ..schemas import ValidatedSpan


class SpanRepository:
    def __init__(self, db):
        self._db = db

    def exists(self, trace_id: str, span_id: str) -> bool:
        row = self._db.conn.execute(
            "SELECT 1 FROM spans WHERE trace_id = ? AND span_id = ?",
            (trace_id, span_id),
        ).fetchone()
        return row is not None

    def insert_if_absent(self, span: ValidatedSpan, arrival_ns: int) -> bool:
        """插入片段；已存在（重复上报）则忽略，返回是否为首次插入。"""
        cur = self._db.conn.execute(
            """
            INSERT OR IGNORE INTO spans
                (trace_id, span_id, parent_span_id, service,
                 start_ns, end_ns, duration_ms, status_code, arrival_ns)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                span.trace_id,
                span.span_id,
                span.parent_span_id,
                span.service,
                span.start_ns,
                span.end_ns,
                span.duration_ms,
                span.status_code,
                arrival_ns,
            ),
        )
        return cur.rowcount > 0

    def span_ids(self, trace_id: str) -> set[str]:
        rows = self._db.conn.execute(
            "SELECT span_id FROM spans WHERE trace_id = ?", (trace_id,)
        ).fetchall()
        return {r["span_id"] for r in rows}

    def list_by_trace(self, trace_id: str) -> list[sqlite3.Row]:
        return self._db.conn.execute(
            "SELECT * FROM spans WHERE trace_id = ?", (trace_id,)
        ).fetchall()

    def trace_exists(self, trace_id: str) -> bool:
        row = self._db.conn.execute(
            "SELECT 1 FROM spans WHERE trace_id = ? LIMIT 1", (trace_id,)
        ).fetchone()
        return row is not None

    def list_traces(
        self, trace_id_like: str | None, service: str | None, limit: int
    ) -> list[sqlite3.Row]:
        """检索列表：按 trace_id 前缀/包含匹配，或按服务名过滤，取最新上报的若干条。"""
        sql = "SELECT * FROM spans WHERE 1=1"
        params: list = []
        if trace_id_like:
            sql += " AND trace_id LIKE ?"
            params.append(f"%{trace_id_like}%")
        if service:
            sql += " AND service LIKE ?"
            params.append(f"%{service}%")
        sql += " ORDER BY arrival_ns DESC LIMIT ?"
        params.append(limit)
        return self._db.conn.execute(sql, params).fetchall()
