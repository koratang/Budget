"""增量重算服务（写回派生值）与数据库层约束：锁定版本、锁定汇率、审计只追加、预置角色与规则。"""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.calc.recalc import recalc_b2b_units, recalc_for_fx_change, recalc_platform_units
from app.core.audit import write_audit
from app.core.money import fmt_amount
from app.models import (AuditLog, B2bUnit, BCustomer, BudgetVersion, Category, ChannelCategoryRatio, ChannelSiteRatio,
                        FxBudget, PlatformUnit, Role, Rule, RuleVersion, Site, Store)

MAR = date(2027, 3, 1)


def make_version(db, locked=False, type_="draft"):
    v = BudgetVersion(year=2027, type=type_, version_no=1, name="2027 年度预算编制稿", locked=locked)
    db.add(v)
    db.flush()
    return v


def flow11_unit(db, version):
    store = db.scalar(select(Store).where(Store.name == "Amazon-US-01"))
    cat = db.scalar(select(Category.id).where(Category.name == "浴室柜"))
    unit = PlatformUnit(version_id=version.id, month=MAR, channel_id=store.channel_id, store_id=store.id,
                        site_id=store.site_id, category_id=cat, is_new=True, spu_count=10, avg_sales=D("120"),
                        avg_price=D("80.00"), discount_rate=D("0.10"), refund_rate=D("0.05"), ad_rate=D("0.12"),
                        commission_rate=D("0.15"))
    db.add_all([
        unit,
        ChannelCategoryRatio(version_id=version.id, month=MAR, channel_id=store.channel_id, site_id=store.site_id,
                             category_id=cat, purchase_cost_rate=D("0.30"), first_leg_rate=D("0.06"),
                             last_mile_rate=D("0.08"), storage_rate=D("0.02"), tariff_rate=D("0.04")),
        ChannelSiteRatio(version_id=version.id, month=MAR, channel_id=store.channel_id, site_id=store.site_id,
                         inventory_claim_rate=D("0.01"), other_opex_rate=D("0.03")),
    ])
    db.flush()
    return unit


def test_recalc_platform_unit_writes_derived_values(seeded):
    db = seeded
    unit = flow11_unit(db, make_version(db))
    [row] = recalc_platform_units(db, unit.version_id, unit_ids=[unit.id])
    db.refresh(row)
    assert fmt_amount(row.revenue_local) == "86,400.00"
    assert fmt_amount(row.revenue_cny) == "615,168.00"
    assert fmt_amount(row.gross_profit) == "98,426.88"
    assert row.gross_margin == D("0.16")

    # 比率变化 → 按维度批量重算（库存索赔率 1% → 0%：毛利减少 6,151.68）
    db.execute(text("UPDATE channel_site_ratio SET inventory_claim_rate = 0"))
    recalc_platform_units(db, unit.version_id, month=MAR, channel_id=unit.channel_id, site_id=unit.site_id)
    db.refresh(row)
    assert fmt_amount(row.gross_profit) == "92,275.20"


def test_recalc_b2b_and_fx_change(seeded):
    db = seeded
    v = make_version(db)
    ferguson = db.scalar(select(BCustomer.id).where(BCustomer.name == "Ferguson"))
    unit = B2bUnit(version_id=v.id, month=MAR, customer_id=ferguson, sales_local=D("200000.00"),
                   refund_rate=D("0.02"), promotion_rate=D("0.03"), other_opex_rate=D("0.01"),
                   purchase_cost_rate=D("0.55"), first_leg_rate=D("0.05"), last_mile_rate=D("0.02"),
                   storage_rate=D("0.01"), tariff_rate=D("0.07"))
    db.add(unit)
    db.flush()
    recalc_b2b_units(db, v.id, unit_ids=[unit.id])
    assert fmt_amount(unit.revenue_cny) == "1,424,000.00" and fmt_amount(unit.gross_profit) == "341,760.00"

    db.execute(text("UPDATE fx_budget SET rate = 7.00 WHERE year = 2027 AND currency = 'USD'"))
    assert recalc_for_fx_change(db, 2027, "USD") == 1
    assert fmt_amount(unit.revenue_cny) == "1,400,000.00"


def _expect_db_error(db, sql: str, message: str):
    with pytest.raises(DBAPIError) as e:
        with db.begin_nested():
            db.execute(text(sql))
    assert message in str(e.value.orig)


def test_locked_version_rows_cannot_change(seeded):
    db = seeded
    v = make_version(db)
    unit = flow11_unit(db, v)
    db.execute(text("UPDATE budget_version SET locked = true, type = 'original_target' WHERE id = :v"), {"v": v.id})
    _expect_db_error(db, f"UPDATE platform_unit SET spu_count = 11 WHERE id = {unit.id}", "版本已锁定")
    _expect_db_error(db, f"DELETE FROM channel_site_ratio WHERE version_id = {v.id}", "版本已锁定")
    _expect_db_error(db, f"UPDATE budget_version SET locked = false WHERE id = {v.id}", "版本已锁定")
    assert db.scalar(select(PlatformUnit.spu_count).where(PlatformUnit.id == unit.id)) == 10


def test_budget_fx_frozen_after_original_target(seeded):
    db = seeded
    db.execute(text("UPDATE fx_budget SET rate = 7.13 WHERE year = 2027 AND currency = 'USD'"))  # 未锁定可改
    make_version(db, locked=True, type_="original_target")
    _expect_db_error(db, "UPDATE fx_budget SET rate = 7.20 WHERE year = 2027 AND currency = 'USD'",
                     "已随年初原始目标锁定")
    _expect_db_error(db, "DELETE FROM fx_budget WHERE year = 2027 AND currency = 'EUR'", "已随年初原始目标锁定")
    db.add(FxBudget(year=2027, currency="JPY", rate=D("0.047")))  # 尚无汇率的币种允许新增（AC-F02-11）
    db.flush()


def test_audit_log_is_append_only(seeded):
    db = seeded
    row = write_audit(db, action="role_assign", object_type="user", object_id=1, before={"roles": []},
                      after={"roles": ["operations"], "amount": D("1.50")}, actor_name="林晓")
    assert db.get(AuditLog, row.id).after == {"roles": ["operations"], "amount": "1.50"}
    _expect_db_error(db, f"UPDATE audit_log SET action = 'x' WHERE id = {row.id}", "permission denied")
    _expect_db_error(db, f"DELETE FROM audit_log WHERE id = {row.id}", "permission denied")


def test_audit_trigger_blocks_privileged_update(seeded):
    """即使有权限（恢复授权模拟超级账号误用），触发器仍拒绝。"""
    db = seeded
    row = write_audit(db, action="login", object_type="user", object_id=1, actor_name="林晓")
    db.execute(text("GRANT UPDATE, DELETE ON audit_log TO CURRENT_USER"))
    _expect_db_error(db, f"UPDATE audit_log SET action = 'x' WHERE id = {row.id}", "审计日志只允许追加")
    _expect_db_error(db, f"DELETE FROM audit_log WHERE id = {row.id}", "审计日志只允许追加")


def test_unique_open_task_and_rule_version_constraints(seeded):
    db = seeded
    v = make_version(db)
    db.execute(text("INSERT INTO budget_task (name, year, deadline, status, version_id) "
                    "VALUES ('2027 年度预算编制', 2027, '2026-12-20', 'in_progress', :v)"), {"v": v.id})
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(text("INSERT INTO budget_task (name, year, deadline, status, version_id) "
                            "VALUES ('重复任务', 2027, '2026-12-25', 'in_progress', :v)"), {"v": v.id})
    rule_id = db.scalar(select(Rule.id).limit(1))
    with pytest.raises(IntegrityError):  # 已有待审批 v1，再提交待审批版本冲突
        with db.begin_nested():
            db.add(RuleVersion(rule_id=rule_id, version_no=2, content={}, credibility="observed", status="pending"))
            db.flush()


def test_platform_unit_store_must_match_channel_and_site(seeded):
    db = seeded
    v = make_version(db)
    store = db.scalar(select(Store).where(Store.name == "Amazon-US-01"))
    ca_site = db.scalar(select(Site.id).where(Site.code == "CA"))
    cat = db.scalar(select(Category.id).limit(1))
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(PlatformUnit(version_id=v.id, month=MAR, channel_id=store.channel_id, store_id=store.id,
                                site_id=ca_site, category_id=cat, is_new=False))
            db.flush()


def test_initial_migration_presets(db):
    assert db.scalar(select(text("count(*)")).select_from(Role)) == 8
    rows = db.execute(select(Rule.name, Rule.type, RuleVersion.status, RuleVersion.credibility, RuleVersion.version_no)
                      .join(RuleVersion, RuleVersion.rule_id == Rule.id).order_by(Rule.id)).all()
    assert [r[0] for r in rows] == ["新渠道连续 2 个月收入达成率低于 70%", "部门费用额度使用率超出时间进度 10 个百分点以上",
                                    "品类毛利率比预算低 3 个百分点以上"]
    assert {tuple(r[1:]) for r in rows} == {("alert_rule", "pending", "unverified", 1)}
