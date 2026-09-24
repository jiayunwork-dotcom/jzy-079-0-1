"""集中式配置：所有可调参数都从这里读取（环境变量覆盖）。"""
from __future__ import annotations

import os


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


# SQLite 数据文件位置（容器内挂卷持久化）
DB_PATH: str = os.environ.get("TRACE_DB_PATH", "/data/traces.db")

# 子片段等待父片段到达的最长时间（秒），超时后归入「父片段缺失」占位节点
ORPHAN_MAX_WAIT_SECONDS: float = _get_float("ORPHAN_MAX_WAIT_SECONDS", 30.0)

# 依赖图可选时间窗口（秒），默认最近一小时 / 最近一天
DEPENDENCY_WINDOWS_SECONDS: dict[str, int] = {
    "1h": _get_int("DEPENDENCY_WINDOW_1H", 3600),
    "24h": _get_int("DEPENDENCY_WINDOW_24H", 86400),
}
DEFAULT_WINDOW: str = "1h"

# 依赖图后台重算间隔（秒），让滚动窗口的边随时间自然过期
GRAPH_REFRESH_INTERVAL_SECONDS: float = _get_float("GRAPH_REFRESH_INTERVAL_SECONDS", 30.0)

# 单批上报允许的最大片段数，防止异常大请求打爆存储
MAX_BATCH_SIZE: int = _get_int("MAX_BATCH_SIZE", 5000)
