"""孤儿片段等待表的数据访问。"""
from __future__ import annotations


class OrphanRepository:
    def __init__(self, db):
        self._db = db

    def add_waiting(
        self,
        trace_id: str,
        span_id: str,
        parent_span_id: str,
        since_ns: int,
        timeout_ns: int,
    ) -> None:
        # 只有首次插入，避免重复上报把等待状态覆盖掉
        self._db.conn.execute(
            """
            INSERT OR IGNORE INTO orphans
                (trace_id, span_id, parent_span_id, state, since_ns, timeout_ns)
            VALUES (?, ?, ?, 'waiting', ?, ?)
            """,
            (trace_id, span_id, parent_span_id, since_ns, timeout_ns),
        )

    def get(self, trace_id: str, span_id: str):
        return self._db.conn.execute(
            "SELECT * FROM orphans WHERE trace_id = ? AND span_id = ?",
            (trace_id, span_id),
        ).fetchone()

    def mark_resolved(self, trace_id: str, span_id: str) -> None:
        """父片段已到达：只允许 waiting -> resolved，timeout 不可逆。"""
        self._db.conn.execute(
            """
            UPDATE orphans SET state = 'resolved'
            WHERE trace_id = ? AND span_id = ? AND state = 'waiting'
            """,
            (trace_id, span_id),
        )

    def mark_timeout(self, trace_ids_span_ids: list[tuple[str, str]]) -> None:
        """把已到等待上限的 waiting 记录批量标记为 timeout（不可回退）。"""
        if not trace_ids_span_ids:
            return
        self._db.conn.executemany(
            """
            UPDATE orphans SET state = 'timeout'
            WHERE trace_id = ? AND span_id = ? AND state = 'waiting'
            """,
            trace_ids_span_ids,
        )

    def list_expired_waiting(self, now_ns: int) -> list:
        return self._db.conn.execute(
            "SELECT trace_id, span_id FROM orphans WHERE state = 'waiting' AND timeout_ns <= ?",
            (now_ns,),
        ).fetchall()

    def state_map(self, trace_id: str) -> dict[str, str]:
        rows = self._db.conn.execute(
            "SELECT span_id, state FROM orphans WHERE trace_id = ?", (trace_id,)
        ).fetchall()
        return {r["span_id"]: r["state"] for r in rows}
