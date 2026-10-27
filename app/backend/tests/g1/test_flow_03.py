"""FLOW-03 按角色限定数据范围（REQ-F01-03，AC-F01-06~09）：角色 × 资源矩阵，期望值逐字取自 TDD验收契约 FLOW-03。

填报与报表接口（API-F04-02 / API-F05-01 / API-F10-02 / API-F10-04）由 G2、G4 实现，均须经 CMP-F01-03 的
ScopeContext 过滤与 restrict_fields 裁剪；本测试以登录后服务端加载的 ScopeContext 对预算数据表做同一过滤，
覆盖 3 个部门、4 个店铺、3 个 B 端客户的数据行。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.scope import load_scope, restrict_fields
from app.models import (B2bUnit, BCustomer, BudgetVersion, Category, ChannelCategoryRatio, DeptExpense, Department,
                        PlatformUnit, Store, UserRole)
from app.models.enums import VersionType
from tests.g1.helpers import account_id, customer_id, dept_id, login, uid

M = date(2027, 1, 1)
DEPTS = ["人力资源部", "财务部", "市场部"]
STORES = ["Amazon-US-01", "Amazon-CA-01", "Wayfair-US-01", "Lowes-US-01"]
CUSTOMERS = ["Ferguson", "Menards", "Bauhaus"]


def _prepare(db):
    v = BudgetVersion(year=2027, type=VersionType.DRAFT, version_no=1, name="2027 编制稿")
    db.add(v)
    db.flush()
    cat = db.scalar(select(Category.id).where(Category.name == "浴室柜"))
    acc = account_id(db, "培训费")
    for d in DEPTS:
        db.add(DeptExpense(version_id=v.id, month=M, department_id=dept_id(db, d), account_id=acc,
                           amount=Decimal("12000")))
    for name in STORES:
        s = db.scalar(select(Store).where(Store.name == name))
        db.add(PlatformUnit(version_id=v.id, month=M, channel_id=s.channel_id, store_id=s.id, site_id=s.site_id,
                            category_id=cat, is_new=False, spu_count=3, avg_sales=Decimal("100"),
                            avg_price=Decimal("80"), revenue_cny=Decimal("170880"), gross_profit=Decimal("50000")))
    for c in CUSTOMERS:
        db.add(B2bUnit(version_id=v.id, month=M, customer_id=customer_id(db, c), sales_local=Decimal("50000")))
    db.flush()
    return v


def _ctx(db, dingtalk, userid):
    me = login(db, dingtalk, userid).get("/api/me")
    assert me.status_code == 200
    user_id = uid(db, userid)
    return load_scope(db, user_id, db.scalars(select(UserRole.role_code).where(UserRole.user_id == user_id)).all())


def test_department_roles_only_see_own_department(seeded, db, dingtalk):
    v = _prepare(db)
    for userid in ("wujing", "zhengke"):
        ctx = _ctx(db, dingtalk, userid)
        rows = db.scalars(select(Department.name).join(DeptExpense, DeptExpense.department_id == Department.id)
                          .where(DeptExpense.version_id == v.id, ctx.department_clause(DeptExpense.department_id)))
        assert sorted(set(rows)) == ["人力资源部"]


def test_operations_only_sees_assigned_store(seeded, db, dingtalk):
    v = _prepare(db)
    ctx = _ctx(db, dingtalk, "wanghao")
    rows = db.scalars(select(Store.name).join(PlatformUnit, PlatformUnit.store_id == Store.id)
                      .where(PlatformUnit.version_id == v.id,
                             ctx.store_clause(PlatformUnit.store_id, PlatformUnit.channel_id)))
    assert sorted(set(rows)) == ["Amazon-US-01"]


def test_b2b_only_sees_assigned_customers(seeded, db, dingtalk):
    v = _prepare(db)
    ctx = _ctx(db, dingtalk, "sunting")
    rows = db.scalars(select(BCustomer.name).join(B2bUnit, B2bUnit.customer_id == BCustomer.id)
                      .where(B2bUnit.version_id == v.id, ctx.customer_clause(B2bUnit.customer_id)))
    assert sorted(set(rows)) == ["Ferguson", "Menards"]
    assert "Bauhaus" not in rows


def test_logistics_only_four_rates(seeded, db, dingtalk):
    v = _prepare(db)
    ctx = _ctx(db, dingtalk, "jiangfan")
    unit = db.scalar(select(PlatformUnit).where(PlatformUnit.version_id == v.id).limit(1))
    full = {c.key: getattr(unit, c.key) for c in PlatformUnit.__table__.columns}
    full.update(first_leg_rate=Decimal("0.05"), last_mile_rate=Decimal("0.08"), storage_rate=Decimal("0.02"),
                tariff_rate=Decimal("0.07"), purchase_cost_rate=Decimal("0.3"))
    view = restrict_fields(ctx, full)
    for key in ("first_leg_rate", "last_mile_rate", "storage_rate", "tariff_rate"):
        assert key in view
    for key in ("revenue_cny", "revenue_local", "sales_qty", "gross_profit", "gross_margin", "avg_sales",
                "avg_price", "purchase_cost_rate"):
        assert key not in view
    # 物流物控的比例表：维度列 + 四项比例
    ratio = ChannelCategoryRatio(version_id=v.id, month=M, channel_id=unit.channel_id, site_id=unit.site_id,
                                 category_id=unit.category_id)
    ratio_view = restrict_fields(ctx, {c.key: getattr(ratio, c.key) for c in ChannelCategoryRatio.__table__.columns})
    assert set(ratio_view) - {"id", "version_id", "month", "channel_id", "site_id", "category_id", "updated_by",
                              "updated_at"} == {"first_leg_rate", "last_mile_rate", "storage_rate", "tariff_rate"}
