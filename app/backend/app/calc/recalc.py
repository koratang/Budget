"""保存驱动后增量重算单元派生值（DEC-006、SEQ-F04-01、NFR-001）。

在调用方事务内执行（只 flush 不 commit）：
- 运营保存驱动 → recalc_platform_units(db, version_id, unit_ids=[...])
- 财务BP / 物流物控保存「月 × 渠道 × 站点 × 品类」比率 → recalc_platform_units(db, v, month=, channel_id=, site_id=, category_id=)
- 财务BP 保存「月 × 渠道 × 站点」库存索赔 / 其他运营费用率 → recalc_platform_units(db, v, month=, channel_id=, site_id=)
- B 端任一输入 → recalc_b2b_units(db, v, unit_ids=[...]) 或 (month=, customer_id=)
- 锁定前修改预算汇率 → recalc_for_fx_change(db, year, currency)（该年度全部未锁定版本，DEC-020）
锁定版本的行由数据库触发器拒绝修改，调用方不应对锁定版本调用。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.calc.formulas import CostRates, OpexRates, PlatformDrivers, ProfitLines, calc_b2b_unit, calc_platform_unit
from app.models import (B2bUnit, BCustomer, BudgetVersion, ChannelCategoryRatio, ChannelSiteRatio, FxBudget,
                        PlatformUnit, Store)

ZERO = Decimal(0)
_LINE_FIELDS = ("revenue_cny", "refund", "purchase_cost", "commission", "promotion", "first_leg", "last_mile",
                "tariff", "storage", "inventory_claim", "other_opex", "gross_profit", "gross_margin")


def budget_fx_rates(db: Session, year: int) -> dict[str, Decimal]:
    return dict(db.execute(select(FxBudget.currency, FxBudget.rate).where(FxBudget.year == year)).all())


def _apply_lines(row, lines: ProfitLines | None) -> None:
    for f in _LINE_FIELDS:
        setattr(row, f, getattr(lines, f) if lines is not None else None)


def _version_year(db: Session, version_id: int) -> int:
    return db.scalar(select(BudgetVersion.year).where(BudgetVersion.id == version_id))


def recalc_platform_units(db: Session, version_id: int, *, unit_ids: list[int] | None = None,
                          month: date | None = None, store_id: int | None = None, channel_id: int | None = None,
                          site_id: int | None = None, category_id: int | None = None,
                          currency: str | None = None) -> list[PlatformUnit]:
    """重算平台渠道单元派生值（按给定条件筛选受影响单元）并写回，返回被重算的单元。"""
    fx = budget_fx_rates(db, _version_year(db, version_id))
    ccr, csr = ChannelCategoryRatio, ChannelSiteRatio
    q = (
        select(PlatformUnit, Store.currency, ccr, csr)
        .join(Store, Store.id == PlatformUnit.store_id)
        .outerjoin(ccr, and_(ccr.version_id == PlatformUnit.version_id, ccr.month == PlatformUnit.month,
                             ccr.channel_id == PlatformUnit.channel_id, ccr.site_id == PlatformUnit.site_id,
                             ccr.category_id == PlatformUnit.category_id))
        .outerjoin(csr, and_(csr.version_id == PlatformUnit.version_id, csr.month == PlatformUnit.month,
                             csr.channel_id == PlatformUnit.channel_id, csr.site_id == PlatformUnit.site_id))
        .where(PlatformUnit.version_id == version_id)
    )
    if unit_ids is not None:
        q = q.where(PlatformUnit.id.in_(unit_ids))
    for col, val in ((PlatformUnit.month, month), (PlatformUnit.store_id, store_id),
                     (PlatformUnit.channel_id, channel_id), (PlatformUnit.site_id, site_id),
                     (PlatformUnit.category_id, category_id), (Store.currency, currency)):
        if val is not None:
            q = q.where(col == val)
    updated = []
    for unit, cur, cost_row, site_row in db.execute(q).all():
        cost = CostRates(
            purchase_cost_rate=cost_row.purchase_cost_rate, first_leg_rate=cost_row.first_leg_rate,
            last_mile_rate=cost_row.last_mile_rate, storage_rate=cost_row.storage_rate,
            tariff_rate=cost_row.tariff_rate) if cost_row else CostRates()
        result = calc_platform_unit(
            PlatformDrivers(spu_count=unit.spu_count, avg_sales=unit.avg_sales, avg_price=unit.avg_price,
                            discount_rate=unit.discount_rate, refund_rate=unit.refund_rate, ad_rate=unit.ad_rate,
                            commission_rate=unit.commission_rate),
            cost,
            site_row.inventory_claim_rate if site_row else ZERO,
            site_row.other_opex_rate if site_row else ZERO,
            fx.get(cur),
        )
        unit.sales_qty = result.sales_qty
        unit.revenue_local = result.revenue_local
        _apply_lines(unit, result.lines)
        updated.append(unit)
    db.flush()
    return updated


def recalc_b2b_units(db: Session, version_id: int, *, unit_ids: list[int] | None = None, month: date | None = None,
                     customer_id: int | None = None, currency: str | None = None) -> list[B2bUnit]:
    """重算 B 端单元派生值并写回。"""
    fx = budget_fx_rates(db, _version_year(db, version_id))
    q = (select(B2bUnit, BCustomer.currency).join(BCustomer, BCustomer.id == B2bUnit.customer_id)
         .where(B2bUnit.version_id == version_id))
    if unit_ids is not None:
        q = q.where(B2bUnit.id.in_(unit_ids))
    for col, val in ((B2bUnit.month, month), (B2bUnit.customer_id, customer_id), (BCustomer.currency, currency)):
        if val is not None:
            q = q.where(col == val)
    updated = []
    for unit, cur in db.execute(q).all():
        lines = calc_b2b_unit(
            unit.sales_local,
            OpexRates(refund_rate=unit.refund_rate, commission_rate=unit.commission_rate,
                      promotion_rate=unit.promotion_rate, inventory_claim_rate=unit.inventory_claim_rate,
                      other_opex_rate=unit.other_opex_rate),
            CostRates(purchase_cost_rate=unit.purchase_cost_rate, first_leg_rate=unit.first_leg_rate,
                      last_mile_rate=unit.last_mile_rate, storage_rate=unit.storage_rate,
                      tariff_rate=unit.tariff_rate),
            fx.get(cur),
        )
        _apply_lines(unit, lines)
        updated.append(unit)
    db.flush()
    return updated


def recalc_for_fx_change(db: Session, year: int, currency: str) -> int:
    """预算汇率修改后：该年度全部未锁定版本中该币种的平台渠道与 B 端单元重算。返回重算单元数。"""
    version_ids = db.scalars(select(BudgetVersion.id).where(BudgetVersion.year == year,
                                                            BudgetVersion.locked.is_(False))).all()
    count = 0
    for vid in version_ids:
        count += len(recalc_platform_units(db, vid, currency=currency))
        count += len(recalc_b2b_units(db, vid, currency=currency))
    return count
