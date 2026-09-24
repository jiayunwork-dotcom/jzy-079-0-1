"""时间解析工具：片段时间统一转成「纳秒级 Unix 时间戳（int）」存储与比较。

接受两种输入：
- ISO 8601 字符串（必须带时区，如 2026-09-24T10:00:00+00:00 或 ...Z）
- 数值时间戳，按数量级推断单位（秒/毫秒/微秒/纳秒）
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

NS_PER_SECOND = 1_000_000_000
NS_PER_MILLI = 1_000_000
NS_PER_MICRO = 1_000

# 数值单位推断阈值（绝对值）：>1e17 视为纳秒，>1e14 微秒，>1e11 毫秒，否则秒
_NS_THRESHOLD = 10**17
_US_THRESHOLD = 10**14
_MS_THRESHOLD = 10**11


def now_ns() -> int:
    return time.time_ns()


def parse_timestamp_ns(value: object) -> int:
    """把外部输入解析成纳秒时间戳；无法解析时抛 ValueError。"""
    if isinstance(value, bool):
        raise ValueError("时间戳不能是布尔值")
    if isinstance(value, (int, float)):
        return _numeric_to_ns(float(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("时间戳不能为空字符串")
        try:
            return _numeric_to_ns(float(text))
        except ValueError:
            pass
        return _iso_to_ns(text)
    raise ValueError(f"不支持的时间戳类型: {type(value).__name__}")


def _numeric_to_ns(number: float) -> int:
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("时间戳不能是 NaN 或无穷大")
    if number < 0:
        raise ValueError("时间戳不能为负数")
    magnitude = abs(number)
    if magnitude >= _NS_THRESHOLD:
        return int(number)
    if magnitude >= _US_THRESHOLD:
        return int(number * NS_PER_MICRO)
    if magnitude >= _MS_THRESHOLD:
        return int(number * NS_PER_MILLI)
    return int(number * NS_PER_SECOND)


def _iso_to_ns(text: str) -> int:
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"无法解析的时间格式: {text!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("ISO 时间必须带时区信息（如 +00:00 或 Z）")
    seconds = parsed.astimezone(timezone.utc).timestamp()
    return int(seconds * NS_PER_SECOND)


def ns_to_iso(ns: int) -> str:
    """纳秒时间戳转回 ISO 字符串，供 API 输出。"""
    seconds = ns / NS_PER_SECOND
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
