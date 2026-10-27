"""E1 验收环境控制（浏览器 E2E 用，库 budget_acc1 / 钉钉替身 8021）。

只准备契约行写明的初始状态（主数据、人员），不预先完成待验动作。
用法（app/backend 下）：
    .venv/bin/python -m tests.acceptance.e1_env reset <场景>        # 重建库 + 种子 + 场景前置
    .venv/bin/python -m tests.acceptance.e1_env contact-sync        # 触发一次通讯录同步（替身）
    .venv/bin/python -m tests.acceptance.e1_env overdue <ISO 时间>  # 以给定时刻执行逾期检查并投递通知
    .venv/bin/python -m tests.acceptance.e1_env outbox              # 投递发件箱
"""
import os
import sys
from datetime import datetime

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc1")
os.environ.setdefault("DINGTALK_BASE_URL", "http://127.0.0.1:8021")
for k, v in dict(DINGTALK_APP_KEY="stub", DINGTALK_APP_SECRET="stub", DINGTALK_AGENT_ID="10001",
                 DINGTALK_CORP_ID="ding-stub").items():
    os.environ.setdefault(k, v)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, update  # noqa: E402

from app.config import BACKEND_DIR, get_settings  # noqa: E402
from app.core.clock import TZ  # noqa: E402
from app.db import session_factory  # noqa: E402
from app.dingtalk.gateway import DingTalkClient  # noqa: E402
from app.dingtalk.outbox import process_outbox  # noqa: E402
from app.dingtalk.scheduler import run_contact_sync, run_overdue_check  # noqa: E402
from app.models import Store  # noqa: E402
from scripts.seed import seed  # noqa: E402

URL = os.environ["DATABASE_URL"]


def reset(scenario: str) -> None:
    eng = create_engine(URL)
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    eng.dispose()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["url"] = URL
    command.upgrade(cfg, "head")
    with session_factory(URL)() as db:
        seed(db)
        if scenario == "smoke03":
            from tests.acceptance.e1_helpers import smoke03_master
            smoke03_master(db)
        elif scenario == "flow09":
            from tests.acceptance.e1_helpers import flow09_master
            flow09_master(db)
        elif scenario == "flow03":
            db.execute(update(Store).values(is_active=True))
        db.commit()


def _client() -> DingTalkClient:
    return DingTalkClient(get_settings())


def main(argv: list[str]) -> None:
    cmd = argv[0]
    if cmd == "reset":
        reset(argv[1] if len(argv) > 1 else "default")
    elif cmd == "contact-sync":
        client = _client()
        with session_factory(URL)() as db:
            run_contact_sync(db, client)
            db.commit()
    elif cmd == "overdue":
        now = datetime.fromisoformat(argv[1]).replace(tzinfo=TZ)
        client = _client()
        with session_factory(URL)() as db:
            run_overdue_check(db, now)
            db.commit()
            process_outbox(db, client)
            db.commit()
    elif cmd == "outbox":
        client = _client()
        with session_factory(URL)() as db:
            process_outbox(db, client)
            db.commit()
    print("ok", cmd)


if __name__ == "__main__":
    main(sys.argv[1:])
