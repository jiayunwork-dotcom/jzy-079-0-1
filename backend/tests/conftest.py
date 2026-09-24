import sys
from pathlib import Path

import pytest

# 让测试可以 import 到 app 包（pyproject 未做安装式布局）
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.events import EventHub  # noqa: E402
from app.repositories.db import Database  # noqa: E402
from app.service import TraceService  # noqa: E402

# 测试统一用较短的等待上限，方便超时判据验证
TEST_MAX_WAIT_SECONDS = 1.0


@pytest.fixture
def service(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "ORPHAN_MAX_WAIT_SECONDS", TEST_MAX_WAIT_SECONDS)
    db = Database(":memory:")
    svc = TraceService(db, event_hub=EventHub())
    # assembler 在构造时读取默认配置，这里直接重建保证测试参数生效
    from app.assembler import TreeAssembler

    svc.assembler = TreeAssembler(db, max_wait_seconds=TEST_MAX_WAIT_SECONDS)
    yield svc
    db.close()
