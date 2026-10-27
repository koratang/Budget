"""FLOW-07 预算汇率与当月平均汇率（REQ-F02-04，AC-F02-06/07/08/11；DEC-020）：期望值逐字取自 TDD验收契约 FLOW-07。

填报提交时的缺汇率拦截（API-F04-07）由 G2 调用主数据服务 missing_budget_fx；本测试验证其返回含「EUR」。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select

from app.calc.recalc import recalc_platform_units
from app.core.money import fmt_cny, fmt_foreign
from app.models import (BiActualAgg, BudgetVersion, Category, FxBudget, ImportBatch, PlatformUnit, Store, User)
from app.models.enums import ImportSource, ImportStatus, VersionType
from app.services.masterdata import actual_fx_rate, missing_budget_fx
from tests.g1.helpers import login

APRIL = date(2027, 4, 1)


def _unit_us(db):
    """Amazon-US-01 2027-03 浴室柜老品：4 个 SPU × 平均销量 120 × 平均单价 180 × (1 − 0) = USD 86,400.00。"""
    db.execute(delete(FxBudget).where(FxBudget.year == 2027, FxBudget.currency.in_(("USD", "EUR"))))
    v = BudgetVersion(year=2027, type=VersionType.DRAFT, version_no=1, name="2027 编制稿")
    db.add(v)
    db.flush()
    s = db.scalar(select(Store).where(Store.name == "Amazon-US-01"))
    cat = db.scalar(select(Category.id).where(Category.name == "浴室柜"))
    u = PlatformUnit(version_id=v.id, month=date(2027, 3, 1), channel_id=s.channel_id, store_id=s.id,
                     site_id=s.site_id, category_id=cat, is_new=False, spu_count=4, avg_sales=Decimal("120"),
                     avg_price=Decimal("180"))
    db.add(u)
    db.flush()
    recalc_platform_units(db, v.id, unit_ids=[u.id])
    return u


def test_budget_fx_converts_and_missing_currency_blocks(seeded, db, dingtalk):
    u = _unit_us(db)
    assert u.revenue_cny is None
    bp = login(db, dingtalk, "chensiyu")
    r = bp.put("/api/master/fx/budget", json={"year": 2027, "currency": "USD", "rate": "7.12"})
    assert r.status_code == 200, r.text
    db.refresh(u)
    assert fmt_foreign(u.revenue_local, "USD") == "$ 86,400.00 USD"
    assert fmt_cny(u.revenue_cny) == "¥ 615,168.00"

    # Amazon-DE-01 结算币种 EUR，2027 无 EUR 预算汇率
    assert missing_budget_fx(db, 2027, ["USD", "EUR"]) == ["EUR"]
    assert "EUR" in bp.get("/api/master/fx/budget", params={"year": 2027}).json()["missing"]

    assert bp.put("/api/master/fx/budget", json={"year": 2027, "currency": "GBP", "rate": "9.31256"}).json()[
        "message"] == "请输入大于 0 的数字，最多 4 位小数"


def test_actual_monthly_average_rate(seeded, db, dingtalk):
    s = db.scalar(select(Store).where(Store.name == "Amazon-US-01"))
    uploader = db.scalar(select(User.id).where(User.dingtalk_userid == "chensiyu"))
    batch = ImportBatch(source=ImportSource.BI, period=APRIL, file_name="BI销售_2027-04.xlsx",
                        status=ImportStatus.EFFECTIVE, uploaded_by=uploader)
    db.add(batch)
    db.flush()
    agg = BiActualAgg(batch_id=batch.id, month=APRIL, store_id=s.id, site_id=s.site_id,
                      category_id=db.scalar(select(Category.id).where(Category.name == "浴室柜")), is_new=False,
                      spu_count=3, qty=Decimal("400"), revenue_local=Decimal("77000.00"), currency="USD")
    db.add(agg)
    db.flush()
    bp = login(db, dingtalk, "chensiyu")
    r = bp.put("/api/master/fx/actual", json={"month": "2027-04", "currency": "USD", "rate": "7.2000"})
    assert r.status_code == 200 and r.json()["rate"] == "7.2000"
    assert actual_fx_rate(db, APRIL, "USD") == Decimal("7.2000")
    db.refresh(agg)
    assert fmt_cny(agg.revenue_cny) == "¥ 554,400.00"


def test_budget_fx_frozen_after_original_target_locked(seeded, db, dingtalk):
    bp = login(db, dingtalk, "chensiyu")
    assert bp.put("/api/master/fx/budget", json={"year": 2027, "currency": "USD", "rate": "7.12"}).status_code == 200
    db.add(BudgetVersion(year=2027, type=VersionType.ORIGINAL_TARGET, version_no=1, name="2027 年初原始目标",
                         locked=True))
    db.flush()
    page = bp.get("/api/master/fx/budget", params={"year": 2027}).json()
    assert page["locked"] is True and page["lock_message"] == "已随年初原始目标锁定"
    r = bp.put("/api/master/fx/budget", json={"year": 2027, "currency": "USD", "rate": "7.20"})
    assert r.status_code == 409 and r.json()["code"] == "fx_locked"
    assert r.json()["message"] == "已随年初原始目标锁定"
    usd = next(i for i in bp.get("/api/master/fx/budget", params={"year": 2027}).json()["items"]
               if i["currency"] == "USD")
    assert Decimal(usd["rate"]) == Decimal("7.12") and usd["editable"] is False
    r = bp.put("/api/master/fx/budget", json={"year": 2027, "currency": "JPY", "rate": "0.0478"})
    assert r.status_code == 200
    assert db.scalar(select(FxBudget.rate).where(FxBudget.year == 2027, FxBudget.currency == "JPY")) == Decimal("0.0478")
