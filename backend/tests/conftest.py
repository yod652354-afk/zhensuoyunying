"""验收测试配置：独立测试库 + 种子数据。

每次会话开始前重建测试库，避免持久化残留（例如 events 累积超过
游标分页 limit 导致 A17 补偿断言假失败），保证 43 项基线测试确定性通过。
"""
import os
from pathlib import Path

# DATABASE_URL 为相对路径（sqlite:///./test_clinicos.db），实际位于进程 CWD（backend/）。
# 同时清理 tests/ 目录内可能的历史残留，保证每次运行从零开始。
for _p in (Path.cwd() / "test_clinicos.db", Path(__file__).resolve().parent / "test_clinicos.db"):
    if _p.exists():
        _p.unlink()

os.environ["DATABASE_URL"] = "sqlite:///./test_clinicos.db"
os.environ["SEED_DEMO_DATA"] = "true"
os.environ["API_KEYS"] = "test-key"
os.environ["WEBHOOK_DELIVERY_MODE"] = "log"
os.environ["ENVIRONMENT"] = "development"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    """会话级自动执行：确保数据库表存在（服务级测试不依赖 client fixture）。"""
    from app.database import Base, SessionLocal, engine
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    from app.seed import run as seed_run
    with SessionLocal() as db:
        seed_run(db)
    yield


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def headers():
    return {"X-API-Key": "test-key"}


@pytest.fixture(scope="session")
def base(client, headers):
    return {"client": client, "headers": headers}