"""测试基座：budget_test 库每次会话重建（DROP SCHEMA + alembic upgrade head），每个测试在事务内执行、结束回滚。

- db：绑定外层事务的会话（join_transaction_mode=create_savepoint），业务代码里的 commit 只释放保存点。
- app / client：开发配置应用（开发身份开启、调度器关闭），get_db 覆盖为同一会话；钉钉指向进程内替身 dingtalk_stub。
- seeded：写入 scripts/seed.py 的样例主数据与人员。
"""
import os

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL",
                                   "postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_test")
# app.main 在导入时按环境变量建应用，先指向测试库
os.environ.update(DATABASE_URL=TEST_DATABASE_URL, APP_ENV="dev", DEV_IDENTITY_SWITCH="true",
                  SCHEDULER_ENABLED="false")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import BACKEND_DIR, load_settings  # noqa: E402
from app.core.clock import clock  # noqa: E402
from app.db import get_db  # noqa: E402
from app.dingtalk.gateway import DingTalkClient  # noqa: E402
from app.main import create_app  # noqa: E402
from dingtalk_stub.main import app as stub_app  # noqa: E402
from dingtalk_stub.main import stub_reset  # noqa: E402
from scripts.seed import seed  # noqa: E402

STUB_BASE = "http://dingtalk-stub.local"
DINGTALK_CREDS = dict(DINGTALK_BASE_URL=STUB_BASE, DINGTALK_APP_KEY="stub-key", DINGTALK_APP_SECRET="stub-secret",
                      DINGTALK_AGENT_ID="10001", DINGTALK_CORP_ID="ding-stub-corp")


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DATABASE_URL)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["url"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()
        clock.set_now(None)


@pytest.fixture
def seeded(db):
    seed(db)
    return db


@pytest.fixture
def stub():
    """进程内钉钉替身（每个测试复位通讯录、通知记录与失败接收人）。"""
    stub_reset()
    with TestClient(stub_app, base_url=STUB_BASE) as c:
        yield c
    stub_reset()


def make_settings(**overrides):
    base = dict(DATABASE_URL=TEST_DATABASE_URL, APP_ENV="dev", DEV_IDENTITY_SWITCH=True, SCHEDULER_ENABLED=False,
                **DINGTALK_CREDS)
    base.update(overrides)
    return load_settings(**base)


@pytest.fixture
def dingtalk(stub):
    settings = make_settings()
    client = DingTalkClient(settings, transport=stub._transport)
    yield client
    client.close()


def build_client(db, dingtalk_client, **setting_overrides) -> TestClient:
    settings = make_settings(**setting_overrides)
    app = create_app(settings, dingtalk=dingtalk_client)

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return TestClient(app, base_url="http://testserver")


@pytest.fixture
def client(db, dingtalk):
    return build_client(db, dingtalk)
