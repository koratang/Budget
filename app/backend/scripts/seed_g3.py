"""G3 页面联调的前置条件（幂等）：只写前置数据，不预先完成待验收动作。

- 2027 年初原始目标 V1（CEO 已审批锁定）：各启用店铺 × 12 个月的平台渠道收入与毛利、部门费用全年预算；
- SKU 对照表样例（含 FM-2416-WH，首次上架 2026-03-15）；
- 2027-03、2027-04 的 USD 当月平均汇率（GBP 故意不录，用于核对页缺汇率提示）。
用法：cd app/backend && .venv/bin/python -m scripts.seed_g3 [--database-url URL]（先运行 scripts.seed）
"""
import argparse
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.clock import TZ
from app.db import session_factory
from app.models import (BudgetAccount, BudgetVersion, Category, Department, DeptExpense, FxActual, PlatformUnit, Sku,
                        Spu, Store, User)
from app.models.enums import VersionType

SKUS = [("FM-2416-WH", "SPU-FM-2416", "框镜", "2026-03-15"), ("LM-3020-BK", "SPU-LM-3020", "灯镜", "2024-06-01"),
        ("MC-1810-OK", "SPU-MC-1810", "镜柜", "2025-01-10"), ("SD-6070-CL", "SPU-SD-6070", "浴室门", "2023-09-01"),
        ("BT-1708-WH", "SPU-BT-1708", "浴室柜", "2026-09-01")]
# 店铺月人民币收入（预算）与毛利率
STORE_REVENUE = {"Amazon-US-01": 600000, "Amazon-CA-01": 130000, "Amazon-UK-01": 100000, "Amazon-DE-01": 80000,
                 "Wayfair-US-01": 350000, "HomeDepot-US-01": 220000, "Lowes-US-01": 90000, "Lowes-US-02": 60000,
                 "Shopify-US-01": 70000, "TikTok-US-01": 50000}
DEPT_BUDGET = {"人力资源部": 1200000, "物流物控部": 1200000, "运营部": 2400000, "财务部": 900000}


def seed_g3(db: Session) -> dict:
    year = 2027
    v1 = db.scalar(select(BudgetVersion).where(BudgetVersion.year == year,
                                               BudgetVersion.type == VersionType.ORIGINAL_TARGET))
    if v1 is None:
        ceo = db.scalar(select(User).where(User.dingtalk_userid == "zhoumingyuan"))
        v1 = BudgetVersion(year=year, type=VersionType.ORIGINAL_TARGET, version_no=1, name=f"{year} 年初原始目标",
                           approved_by=ceo.id, approved_at=datetime(2026, 12, 28, 17, 30, tzinfo=TZ),
                           published_on=date(2026, 12, 28), locked=False)
        db.add(v1)
        db.flush()
        cat = db.scalar(select(Category).where(Category.name == "浴室柜"))
        for name, rev in STORE_REVENUE.items():
            s = db.scalar(select(Store).where(Store.name == name))
            for m in range(1, 13):
                revenue = Decimal(rev) * (Decimal("1.2") if m in (7, 11) else 1)
                db.add(PlatformUnit(version_id=v1.id, month=date(year, m, 1), channel_id=s.channel_id, store_id=s.id,
                                    site_id=s.site_id, category_id=cat.id, is_new=False, revenue_cny=revenue,
                                    gross_profit=revenue * Decimal("0.25"), gross_margin=Decimal("0.25")))
        acct = db.scalar(select(BudgetAccount).where(BudgetAccount.name == "工资薪酬"))
        for dept_name, annual in DEPT_BUDGET.items():
            d = db.scalar(select(Department).where(Department.name == dept_name))
            for m in range(1, 13):
                db.add(DeptExpense(version_id=v1.id, month=date(year, m, 1), department_id=d.id, account_id=acct.id,
                                   amount=Decimal(annual) / 12))
        db.flush()
        v1.locked = True
    for code, spu_code, cat_name, listed in SKUS:
        if db.scalar(select(Sku).where(Sku.code == code)):
            continue
        spu = db.scalar(select(Spu).where(Spu.code == spu_code))
        if spu is None:
            cat = db.scalar(select(Category).where(Category.name == cat_name))
            spu = Spu(code=spu_code, category_id=cat.id, first_listed_on=date.fromisoformat(listed))
            db.add(spu)
            db.flush()
        db.add(Sku(code=code, spu_id=spu.id, listed_on=date.fromisoformat(listed)))
    for m in (3, 4):
        if not db.scalar(select(FxActual).where(FxActual.month == date(year, m, 1), FxActual.currency == "USD")):
            db.add(FxActual(month=date(year, m, 1), currency="USD", rate=Decimal("7.2000")))
    db.commit()
    return {"original_target_id": v1.id, "skus": len(SKUS)}


def main() -> None:
    parser = argparse.ArgumentParser(description="写入 G3 页面联调前置条件")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    with session_factory(args.database_url or get_settings().DATABASE_URL)() as db:
        print(seed_g3(db))


if __name__ == "__main__":
    main()
