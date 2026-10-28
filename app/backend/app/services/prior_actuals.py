"""上年实际（REQ-F04-06 填报参考、REQ-F10-07 同比）：按店铺 / B 端客户读取某年各月的毛利口径实际。

实际来源与偏差报告一致：kingdee_actual 中已生效批次（金蝶月度、历史金蝶、经营历史表），只取毛利口径科目。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calc.formulas import gross_margin
from app.calc.periods import fmt_month, year_months
from app.core.money import fmt_amount, fmt_cny, fmt_percent
from app.models import BudgetAccount, ImportBatch, KingdeeActual
from app.models.enums import ImportStatus

ZERO = Decimal(0)
GP_ITEMS = ("revenue", "refund", "purchase_cost", "commission", "promotion", "first_leg", "last_mile", "tariff",
            "storage", "inventory_claim", "other_opex")
POSITIVE = frozenset({"revenue", "inventory_claim"})
# 参考行：(键, 名称, 取值)；费率 = 该项实际 ÷ 人民币收入，对应填报的驱动比率
REF_ITEMS = (("revenue", "收入（人民币）"), ("gross_profit", "毛利（人民币）"), ("gross_margin", "毛利率"),
             ("refund_rate", "退款率"), ("promotion_rate", "推广费用率"), ("commission_rate", "佣金率"))
_RATE_OF = {"refund_rate": "refund", "promotion_rate": "promotion", "commission_rate": "commission"}


def gross_profit_of(items: dict[str, Decimal]) -> Decimal:
    return sum((v if k in POSITIVE else -v for k, v in items.items() if k in GP_ITEMS), ZERO)


def by_month(db: Session, year: int, *, store_ids: list[int] | None = None,
             customer_ids: list[int] | None = None) -> dict[date, dict[str, Decimal]]:
    """{月: {损益口径: 金额}}，只含有实际的月份。store_ids / customer_ids 二选一。"""
    q = (select(KingdeeActual.month, BudgetAccount.pl_item, func.sum(KingdeeActual.amount))
         .join(BudgetAccount, BudgetAccount.id == KingdeeActual.account_id)
         .join(ImportBatch, ImportBatch.id == KingdeeActual.batch_id)
         .where(ImportBatch.status == ImportStatus.EFFECTIVE, BudgetAccount.is_dept_expense.is_(False),
                BudgetAccount.pl_item.in_(GP_ITEMS), KingdeeActual.month >= date(year, 1, 1),
                KingdeeActual.month <= date(year, 12, 1))
         .group_by(KingdeeActual.month, BudgetAccount.pl_item))
    if store_ids is not None:
        q = q.where(KingdeeActual.store_id.in_(store_ids or [0]))
    if customer_ids is not None:
        q = q.where(KingdeeActual.customer_id.in_(customer_ids or [0]))
    out: dict[date, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for m, item, amount in db.execute(q).all():
        out[m][item] += amount or ZERO
    return {m: dict(v) for m, v in out.items()}


def _value(key: str, items: dict[str, Decimal]) -> Decimal | None:
    rev = items.get("revenue", ZERO)
    if key == "revenue":
        return rev
    gp = gross_profit_of(items)
    if key == "gross_profit":
        return gp
    if key == "gross_margin":
        return gross_margin(gp, rev) if rev else None
    return items.get(_RATE_OF[key], ZERO) / rev if rev else None


def _fmt(key: str, v: Decimal | None) -> str:
    if v is None:
        return "—"
    return fmt_amount(v) if is_amount(key) else fmt_percent(v, 2)


def ref_values(prior: dict[date, dict[str, Decimal]], budget_year: int) -> list[tuple[str, str, list, Decimal | None]]:
    """参考行取值：[(键, 名称, 本年 1–12 月列对应的上年同月值, 全年列 = 已导入月份合计口径)]；无实际的月份为 None。"""
    total: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for items in prior.values():
        for k, v in items.items():
            total[k] += v
    out = []
    for key, label in REF_ITEMS:
        months = []
        for m in year_months(budget_year):
            items = prior.get(date(budget_year - 1, m.month, 1))
            months.append(_value(key, items) if items else None)
        out.append((key, label, months, _value(key, dict(total)) if prior else None))
    return out


def is_amount(key: str) -> bool:
    return key in ("revenue", "gross_profit")


def ref_rows(prior: dict[date, dict[str, Decimal]], budget_year: int, *, key_prefix: str,
             dims: dict[str, str], label_key: str, label_prefix: str = "") -> list[dict]:
    """填报表格的上年同月实际参考行（只读）：上年某月的值放在本年同月列；无上年实际时不出参考行。"""
    if not prior:
        return []
    cols = [fmt_month(m) for m in year_months(budget_year)]
    return [{"key": f"{key_prefix}|{key}", "kind": "ref",
             "values": {**dims, label_key: label_prefix + label, **{c: _fmt(key, v) for c, v in zip(cols, months)},
                        "year_total": _fmt(key, year_total)}}
            for key, label, months, year_total in ref_values(prior, budget_year)]


def kpi(prior: dict[date, dict[str, Decimal]], year: int) -> dict | None:
    if not prior:
        return None
    total: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for items in prior.values():
        for k, v in items.items():
            total[k] += v
    months = sorted(prior)
    rev, gp = total.get("revenue", ZERO), gross_profit_of(dict(total))
    span = f"{months[0].month} 月" if len(months) == 1 else f"{months[0].month}–{months[-1].month} 月"
    return {"year": year, "months": len(months), "span": span, "revenue_display": fmt_cny(rev),
            "gross_profit_display": fmt_cny(gp), "gross_margin_display": fmt_percent(gross_margin(gp, rev), 1)
            if rev else "—"}


def growth(cur: Decimal | None, prior: Decimal | None) -> Decimal | None:
    """同比增速 =（本期 − 上年同期）÷ |上年同期|；上年同期为 0 或缺失时无增速。"""
    if cur is None or prior is None or prior == 0:
        return None
    return (cur - prior) / abs(prior)
