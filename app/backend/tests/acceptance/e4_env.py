"""E4 验收环境控制（库 budget_acc4）。只准备契约行写明的初始状态，不预先完成待验动作。
用法（app/backend 下）：.venv/bin/python -m tests.acceptance.e4_env reset [rule02]
"""
import os
import sys

ACC4_URL = "postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc4"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402

from app.config import BACKEND_DIR  # noqa: E402
from app.db import session_factory  # noqa: E402
from app.models import Department  # noqa: E402
from scripts.seed import seed  # noqa: E402



def reset(scenario: str = "", url: str = ACC4_URL) -> None:
    """只重建 E4 应用库 budget_acc4（不读 DATABASE_URL，避免误删测试库）。"""
    assert url.endswith("/budget_acc4"), url
    URL = url
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
        if scenario == "rule02":
            from tests.g2.helpers import add_user
            mkt = db.scalar(select(Department).where(Department.name == "市场部")).id
            add_user(db, "liumin", "刘敏", "市场部", ["dept_budget"], {"department": [mkt]})
            add_user(db, "chenhao", "陈浩", "市场部", ["dept_head"], {"department": [mkt]}, head=True)
        elif scenario == "rule09":  # BI 校验需要的 SKU 对照（与 G3 样例相同）
            from datetime import date

            from app.models import Category, Sku, Spu
            from tests.g3.fixtures_g3 import SKUS
            for code, spu_code, cat, listed in SKUS:
                spu = db.scalar(select(Spu).where(Spu.code == spu_code))
                if spu is None:
                    spu = Spu(code=spu_code, category_id=db.scalar(select(Category.id).where(Category.name == cat)),
                              first_listed_on=date.fromisoformat(listed))
                    db.add(spu)
                    db.flush()
                db.add(Sku(code=code, spu_id=spu.id, listed_on=date.fromisoformat(listed)))
        db.commit()


def bulk(target: int = 20000) -> int:
    """RULE-08 前置：在最新编制稿版本中追加「压测店铺」平台单元，使预算单元（platform_unit 行）总数 ≥ target。"""
    from decimal import Decimal

    from sqlalchemy import func, insert

    from app.calc.periods import year_months
    from app.models import BudgetVersion, Category, PlatformUnit, Store
    with session_factory(ACC4_URL)() as db:
        v = db.scalar(select(BudgetVersion).where(BudgetVersion.type == "draft").order_by(BudgetVersion.id.desc()))
        base = db.scalar(select(Store).where(Store.name == "Amazon-US-01"))
        cats = list(db.scalars(select(Category.id)))
        months = year_months(v.year)
        n = 0
        while db.scalar(select(func.count()).select_from(PlatformUnit)) < target:
            st = Store(name=f"压测店铺-{n + 1:03d}", channel_id=base.channel_id, site_id=base.site_id, currency="USD")
            db.add(st)
            db.flush()
            db.execute(insert(PlatformUnit), [dict(version_id=v.id, month=m, channel_id=st.channel_id, store_id=st.id,
                                                    site_id=st.site_id, category_id=c, is_new=nw, spu_count=3,
                                                    avg_sales=Decimal("40"), avg_price=Decimal("59.99"))
                                               for m in months for c in cats for nw in (True, False)])
            n += 1
        db.commit()
        return db.scalar(select(func.count()).select_from(PlatformUnit))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    if cmd == "reset":
        reset(*args)
        print("ok")
    elif cmd == "gen09":  # RULE-09 样例：5 万行金蝶与 BI，各一份合法版与末行出错版
        from pathlib import Path

        from tests.g3.fixtures_g3 import BI_HEADER, KINGDEE_HEADER, write_xlsx
        from tests.g3.test_rule_09 import bi_rows, kingdee_rows
        out = Path(args[0])
        for name, header, rows in (("金蝶_5万行_合法.xlsx", KINGDEE_HEADER, kingdee_rows(False)),
                                   ("金蝶_5万行_末行出错.xlsx", KINGDEE_HEADER, kingdee_rows(True)),
                                   ("BI_5万行_合法.xlsx", BI_HEADER, bi_rows(False)),
                                   ("BI_5万行_末行出错.xlsx", BI_HEADER, bi_rows(True))):
            write_xlsx(out / name, header, rows)
        print("ok")
    elif cmd == "bulk":
        print(bulk(*(int(a) for a in args)))
