"""聚合后服务依赖边的数据访问（按时间桶存，桶内累加次数与总耗时）。"""
from __future__ import annotations

import sqlite3


class DependencyRepository:
    def __init__(self, db):
        self._db = db

    def add_call(
        self,
        caller_service: str,
        callee_service: str,
        bucket_ns: int,
        duration_ms: float,
    ) -> None:
        """累加一条调用到对应时间桶。"""
        self._db.conn.execute(
            """
            INSERT INTO dep_edges
                (caller_service, callee_service, bucket_ns, count, total_duration_ms)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(caller_service, callee_service, bucket_ns) DO UPDATE SET
                count = count + 1,
                total_duration_ms = total_duration_ms + excluded.total_duration_ms
            """,
            (caller_service, callee_service, bucket_ns, duration_ms),
        )

    def aggregate_since(self, since_bucket_ns: int) -> list[sqlite3.Row]:
        """按时间桶下界把调用边二次聚合成 caller->callee 的次数与总耗时。"""
        return self._db.conn.execute(
            """
            SELECT caller_service AS caller, callee_service AS callee,
                   SUM(count) AS count, SUM(total_duration_ms) AS total_duration_ms
            FROM dep_edges
            WHERE bucket_ns >= ?
            GROUP BY caller_service, callee_service
            """,
            (since_bucket_ns,),
        ).fetchall()
