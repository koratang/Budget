"""偏差报告服务（API-F10-01~05，技术方案 §4.3 / §4.5，DEC-024、DEC-025）。

- 预算值读取 G2 写入的预算表（platform_unit / b2b_unit / dept_expense / reserve / company_other_pl）派生列；
  实际值读取 G3 写入的实际数表（kingdee_actual / bi_actual_agg），只取「已生效」批次（被替换批次保留但不参与计算）。
- 所有查询经 ScopeContext 过滤；导出（exporter.py）复用本模块同一函数，因此导出天然只含范围内的行（AC-F14-01）。
- 接口值一律字符串：金额为未舍入十进制，比率为百分数字符串；前端只格式化不计算（DEC-005）。

金蝶实际损益口径（金额按利润表方向为正数）：收入、库存索赔为正向，其余损益科目（退款、各项成本费用、部门费用、
财务费用、汇兑损益、营业外收支、所得税）为扣减项。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.calc import formulas as F
from app.calc.periods import fmt_month, parse_month, quarter_of
from app.core.clock import TZ, clock
from app.core.errors import Forbidden, ValidationFailed
from app.core.money import dec_str, ratio_to_percent
from app.core.scope import ScopeContext
from app.models import (B2bUnit, BCustomer, BiActualAgg, BudgetAccount, BudgetVersion, Category, Channel,
                        CompanyOtherPl, Department, DeptExpense, FxActual, FxBudget, ImportBatch, KingdeeActual,
                        PlatformUnit, Reserve, Site, SnapshotMonth, Store, User, VarianceNote)
from app.models.enums import ImportStatus, Role, VersionType

ZERO = Decimal(0)
HUNDRED = Decimal(100)
TWELVE = Decimal(12)

# 毛利口径的十项费用（顺序即页面明细顺序，AC-F06-03）
COST_ITEMS: list[tuple[str, str]] = [
    ("refund", "退款"), ("purchase_cost", "采购成本"), ("commission", "佣金"), ("promotion", "推广费用"),
    ("first_leg", "头程费"), ("last_mile", "尾程费"), ("tariff", "关税"), ("storage", "仓储费"),
    ("inventory_claim", "库存索赔"), ("other_opex", "其他运营费用"),
]
GP_ITEMS = ("revenue",) + tuple(k for k, _ in COST_ITEMS)
POSITIVE_ITEMS = frozenset({"revenue", "inventory_claim"})
OTHER_PL_ITEMS = ("finance_cost", "fx_gain_loss", "non_operating", "income_tax")

BASELINES = {"orig": "年初原始目标", "adj": "最新调整后目标", "roll": "最新滚动预测"}
NOTE_EMPTY_MESSAGE = "请填写说明内容"
REPORT_TYPES = {"channel-site": ("store", "customer", "unassigned"), "category": ("category",),
                "dept-expense": ("dept-account",)}
REPORT_VIEW_ROLES = {
    "company": frozenset({Role.CEO, Role.FINANCE_HEAD, Role.FINANCE_BP}),
}


# ---------------------------------------------------------------------------
# 通用：值转换
# ---------------------------------------------------------------------------
def s(v: Decimal | int | None) -> str | None:
    """接口金额字符串（未舍入）。"""
    if v is None:
        return None
    return dec_str(Decimal(v))


def pct(ratio: Decimal | None) -> str | None:
    """小数比率 → 百分数字符串。"""
    return ratio_to_percent(ratio)


def ratio(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def diff(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if a is None or b is None:
        return None
    return a - b


def gross_profit_of(lines: dict[str, Decimal]) -> Decimal:
    """毛利 = 收入 − 退款 − 采购 − 佣金 − 推广 − 头程 − 尾程 − 关税 − 仓储 + 库存索赔 − 其他运营费用（AC-F06-04）。"""
    total = ZERO
    for item in GP_ITEMS:
        v = lines.get(item, ZERO)
        total += v if item in POSITIVE_ITEMS else -v
    return total


def fmt_time(dt) -> str:
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 版本
# ---------------------------------------------------------------------------
def original_version(db: Session, year: int) -> BudgetVersion | None:
    return db.scalar(select(BudgetVersion).where(BudgetVersion.year == year,
                                                 BudgetVersion.type == VersionType.ORIGINAL_TARGET)
                     .order_by(BudgetVersion.version_no.desc()).limit(1))


def adjusted_version(db: Session, year: int) -> BudgetVersion | None:
    return db.scalar(select(BudgetVersion).where(BudgetVersion.year == year,
                                                 BudgetVersion.type == VersionType.ADJUSTED_TARGET)
                     .order_by(BudgetVersion.version_no.desc()).limit(1))


def rolling_version(db: Session, year: int) -> BudgetVersion | None:
    """最新滚动预测 = 最近发布的季度快照。"""
    return db.scalar(select(BudgetVersion).where(BudgetVersion.year == year,
                                                 BudgetVersion.type == VersionType.SNAPSHOT)
                     .order_by(BudgetVersion.quarter.desc(), BudgetVersion.version_no.desc()).limit(1))


def target_version(db: Session, year: int) -> tuple[BudgetVersion | None, bool]:
    """最新调整后目标（无调整时为年初原始目标）。返回 (版本, 是否回落到原始目标)。"""
    adj = adjusted_version(db, year)
    if adj is not None:
        return adj, False
    return original_version(db, year), True


def data_version_id(db: Session, version: BudgetVersion) -> int:
    """快照可能直接以来源版本发布（Q1 以原始目标作快照）：本版本没有预算行时取来源版本的行。"""
    has_rows = db.scalar(select(func.count()).select_from(PlatformUnit).where(PlatformUnit.version_id == version.id)) \
        or db.scalar(select(func.count()).select_from(B2bUnit).where(B2bUnit.version_id == version.id)) \
        or db.scalar(select(func.count()).select_from(DeptExpense).where(DeptExpense.version_id == version.id))
    if not has_rows and version.source_version_id:
        src = db.get(BudgetVersion, version.source_version_id)
        if src is not None:
            return data_version_id(db, src)
    return version.id


def resolve_baseline(db: Session, year: int, baseline: str) -> tuple[BudgetVersion | None, str]:
    """对比基准（AC-F10-01）→ (版本, 信息条文字)。"""
    orig = original_version(db, year)
    if baseline == "orig":
        return orig, orig.name if orig else "尚无年初原始目标"
    if baseline == "roll":
        roll = rolling_version(db, year)
        if roll is not None:
            return roll, roll.name
        v, _ = target_version(db, year)
        return v, f"尚无已发布的滚动预测快照，取{v.name}" if v else "尚无年初原始目标"
    adj = adjusted_version(db, year)
    if adj is not None:
        return adj, adj.name
    return orig, f"{orig.name}（本年度暂无调整，取年初原始目标）" if orig else "尚无年初原始目标"


def version_brief(v: BudgetVersion | None) -> dict | None:
    if v is None:
        return None
    return {"id": v.id, "name": v.name, "type": v.type, "type_label": VersionType.LABELS.get(v.type, v.type),
            "published_on": v.published_on.isoformat() if v.published_on else None,
            "approved_at": v.approved_at.astimezone(TZ).date().isoformat() if v.approved_at else None}


# ---------------------------------------------------------------------------
# 实际数：已生效批次
# ---------------------------------------------------------------------------
def _effective_batches():
    return select(ImportBatch.id).where(ImportBatch.status == ImportStatus.EFFECTIVE)


def kingdee_months(db: Session) -> list[date]:
    """已导入金蝶实际（生效批次）的月份，升序。"""
    return list(db.scalars(select(KingdeeActual.month).where(KingdeeActual.batch_id.in_(_effective_batches()))
                           .distinct().order_by(KingdeeActual.month)))


def bi_months(db: Session) -> list[date]:
    return list(db.scalars(select(BiActualAgg.month).where(BiActualAgg.batch_id.in_(_effective_batches()))
                           .distinct().order_by(BiActualAgg.month)))


def latest_kingdee_month(db: Session, year: int | None = None) -> date | None:
    months = [m for m in kingdee_months(db) if year is None or m.year == year]
    return months[-1] if months else None


def default_year(db: Session) -> int:
    """报告年度：最近金蝶导入期间所在年度；未导入时取最近的年初原始目标年度；都没有取当前年度。"""
    m = latest_kingdee_month(db)
    if m is not None:
        return m.year
    y = db.scalar(select(func.max(BudgetVersion.year)).where(BudgetVersion.type == VersionType.ORIGINAL_TARGET))
    return y or clock.today().year


def budget_fx(db: Session, year: int) -> dict[str, Decimal]:
    return dict(db.execute(select(FxBudget.currency, FxBudget.rate).where(FxBudget.year == year)).all())


def actual_fx(db: Session, month: date) -> dict[str, Decimal]:
    return dict(db.execute(select(FxActual.currency, FxActual.rate).where(FxActual.month == month)).all())


def _kd_base():
    return (select(KingdeeActual.month, BudgetAccount.pl_item, BudgetAccount.is_dept_expense,
                   func.sum(KingdeeActual.amount))
            .join(BudgetAccount, BudgetAccount.id == KingdeeActual.account_id)
            .where(KingdeeActual.batch_id.in_(_effective_batches())))


@dataclass
class MonthActual:
    revenue: Decimal = ZERO          # 人民币收入（平台 + B 端，金蝶）
    gross_profit: Decimal = ZERO     # 全部毛利口径科目（含未归属渠道）
    dept_expense: Decimal = ZERO     # 部门费用科目
    other: Decimal = ZERO            # 公司层其他损益（扣减）

    @property
    def net_profit(self) -> Decimal:
        """实际净利润 = 毛利合计 − 部门费用 − 公司层其他损益扣减项（AC-F06-07 同口径）。"""
        return self.gross_profit - self.dept_expense - self.other


def monthly_actuals(db: Session, months: list[date]) -> dict[date, MonthActual]:
    """按月汇总全公司金蝶实际（公司汇总只对全公司范围角色开放，不做范围过滤）。"""
    out: dict[date, MonthActual] = {m: MonthActual() for m in months}
    if not months:
        return out
    q = _kd_base().where(KingdeeActual.month.in_(months)).group_by(
        KingdeeActual.month, BudgetAccount.pl_item, BudgetAccount.is_dept_expense)
    for month, item, is_dept, amount in db.execute(q).all():
        a = out[month]
        amount = amount or ZERO
        if is_dept:
            a.dept_expense += amount
        elif item in GP_ITEMS:
            if item == "revenue":
                a.revenue += amount
            a.gross_profit += amount if item in POSITIVE_ITEMS else -amount
        elif item in OTHER_PL_ITEMS:
            a.other += amount
    return out


def target_net_profit(db: Session, version: BudgetVersion | None, months: list[date]) -> dict[date, Decimal]:
    """目标净利润（月）= Σ平台毛利 + ΣB 端毛利 − Σ部门费用（含专项）+ 公司层其他损益（AC-F06-07）。"""
    out = {m: ZERO for m in months}
    if version is None or not months:
        return out
    vid = data_version_id(db, version)
    for model, col, sign in ((PlatformUnit, PlatformUnit.gross_profit, 1), (B2bUnit, B2bUnit.gross_profit, 1),
                             (DeptExpense, DeptExpense.amount, -1), (CompanyOtherPl, CompanyOtherPl.amount, 1)):
        q = (select(model.month, func.coalesce(func.sum(col), 0)).where(model.version_id == vid,
                                                                       model.month.in_(months))
             .group_by(model.month))
        for m, v in db.execute(q).all():
            out[m] += Decimal(v) * sign
    q = (select(Reserve.plan_month, func.sum(Reserve.amount)).where(Reserve.version_id == vid,
                                                                    Reserve.plan_month.in_(months))
         .group_by(Reserve.plan_month))
    for m, v in db.execute(q).all():
        out[m] -= v
    return out


# ---------------------------------------------------------------------------
# 偏差说明（AC-F10-11、API-F10-05）
# ---------------------------------------------------------------------------
def load_notes(db: Session, report_type: str, month: date) -> dict[tuple[str, str], dict]:
    q = (select(VarianceNote, User.name).join(User, User.id == VarianceNote.author_id)
         .where(VarianceNote.report_type == report_type, VarianceNote.month == month))
    return {(n.object_type, n.object_key): note_dict(n, name) for n, name in db.execute(q).all()}


def note_dict(n: VarianceNote, author_name: str) -> dict:
    return {"text": n.note, "author": author_name, "updated_at": fmt_time(n.updated_at)}


def save_note(db: Session, user: User, *, report_type: str, month: str, object_type: str, object_key: str,
              note: str) -> tuple[VarianceNote, dict | None]:
    """保存（覆盖）偏差说明，返回 (说明, 修改前值)；审计由路由写入。"""
    text = (note or "").strip()
    if not text:
        raise ValidationFailed(NOTE_EMPTY_MESSAGE, details={"field": "note"})
    if report_type not in REPORT_TYPES or object_type not in REPORT_TYPES[report_type] or not object_key:
        raise ValidationFailed("偏差说明的报告或对象不合法")
    try:
        m = parse_month(month)
    except ValueError as e:
        raise ValidationFailed(str(e)) from e
    row = db.scalar(select(VarianceNote).where(VarianceNote.report_type == report_type, VarianceNote.month == m,
                                               VarianceNote.object_type == object_type,
                                               VarianceNote.object_key == object_key).with_for_update())
    before = None
    if row is None:
        row = VarianceNote(report_type=report_type, month=m, object_type=object_type, object_key=object_key,
                           note=text, author_id=user.id, updated_at=clock.now())
        db.add(row)
    else:
        before = {"note": row.note, "author_id": row.author_id, "updated_at": row.updated_at}
        row.note, row.author_id, row.updated_at = text, user.id, clock.now()
    db.flush()
    return row, before


# ---------------------------------------------------------------------------
# API-F10-01 公司汇总（AC-F10-08~10）
# ---------------------------------------------------------------------------
def achievement(db: Session, year: int) -> dict | None:
    """累计净利润达成率双口径：年初至最近导入金蝶月实际合计 ÷ 同期目标合计；目标合计 ≤ 0 为空（AC-F10-08）。
    工作台（API-F00-01）与公司汇总共用。没有该年度金蝶实际时返回 None。"""
    last = latest_kingdee_month(db, year)
    if last is None:
        return None
    months = [date(year, m, 1) for m in range(1, last.month + 1)]
    actuals = monthly_actuals(db, months)
    orig = original_version(db, year)
    adj = adjusted_version(db, year)
    orig_np = target_net_profit(db, orig, months)
    adj_np = target_net_profit(db, adj, months) if adj else orig_np
    act_sum = sum((actuals[m].net_profit for m in months), ZERO)
    orig_sum = sum(orig_np.values(), ZERO)
    adj_sum = sum(adj_np.values(), ZERO)
    rate_o = F.net_profit_achievement(act_sum, orig_sum)
    rate_a = F.net_profit_achievement(act_sum, adj_sum)
    return {
        "year": year, "through": fmt_month(last), "period_label": f"{year}-01～{last.month:02d}",
        "actual_sum": s(act_sum),
        "original": {"version": version_brief(orig), "target_sum": s(orig_sum), "rate": pct(rate_o)},
        "adjusted": {"version": version_brief(adj), "has_adjustment": adj is not None, "target_sum": s(adj_sum),
                     "rate": pct(rate_a)},
        "months": [{
            "month": fmt_month(m), "original_target": s(orig_np[m]), "adjusted_target": s(adj_np[m]),
            "actual": s(actuals[m].net_profit),
            "rate_original": pct(F.net_profit_achievement(actuals[m].net_profit, orig_np[m])),
            "rate_adjusted": pct(F.net_profit_achievement(actuals[m].net_profit, adj_np[m])),
        } for m in months],
        "_actuals": actuals,
    }


def growth(db: Session, year: int, last: date, actuals: dict[date, MonthActual]) -> dict:
    """部门费用合计与收入合计相对上年同期增速（AC-F10-09）；上年同期任一月份未导入则不计算。"""
    months_ly = [date(year - 1, m, 1) for m in range(1, last.month + 1)]
    imported = set(kingdee_months(db))
    period = f"{year}-01 至 {fmt_month(last)}"
    period_ly = f"{year - 1}-01 至 {fmt_month(months_ly[-1])}"
    if not all(m in imported for m in months_ly):
        return {"available": False, "message": "上年同期实际未导入，暂不计算增速", "period": period,
                "prior_period": period_ly}
    ly = monthly_actuals(db, months_ly)
    rev_ty = sum((a.revenue for a in actuals.values()), ZERO)
    exp_ty = sum((a.dept_expense for a in actuals.values()), ZERO)
    rev_ly = sum((a.revenue for a in ly.values()), ZERO)
    exp_ly = sum((a.dept_expense for a in ly.values()), ZERO)
    g_rev, g_exp = F.growth_rate(rev_ty, rev_ly), F.growth_rate(exp_ty, exp_ly)
    flagged = F.expense_growth_exceeds(g_exp, g_rev)
    gap = (g_exp - g_rev) * HUNDRED if g_exp is not None and g_rev is not None else None
    return {
        "available": True, "period": period, "prior_period": period_ly,
        "revenue": {"prior": s(rev_ly), "current": s(rev_ty), "increase": s(rev_ty - rev_ly), "growth": pct(g_rev)},
        "dept_expense": {"prior": s(exp_ly), "current": s(exp_ty), "increase": s(exp_ty - exp_ly),
                         "growth": pct(g_exp)},
        "gap_pp": s(gap), "expense_faster": flagged,
    }


def snapshot_quarters(db: Session, year: int) -> list[BudgetVersion]:
    """各季度最近发布的快照（按季度升序）。"""
    rows = db.scalars(select(BudgetVersion).where(BudgetVersion.year == year,
                                                  BudgetVersion.type == VersionType.SNAPSHOT)
                      .order_by(BudgetVersion.quarter, BudgetVersion.version_no)).all()
    latest: dict[int, BudgetVersion] = {}
    for v in rows:
        latest[v.quarter] = v
    return [latest[q] for q in sorted(latest)]


def forecast_accuracy(db: Session, year: int) -> list[dict]:
    """季度预测准确度（AC-F10-10）：所属季度有已发布快照的月份；金蝶已导入时给偏差（百分点），> 1.5 标红。"""
    imported = set(kingdee_months(db))
    out = []
    for snap in snapshot_quarters(db, year):
        snap_rows = db.scalars(select(SnapshotMonth).where(SnapshotMonth.version_id == snap.id)
                               .order_by(SnapshotMonth.month)).all()
        in_q = [r for r in snap_rows if r.month.year == year and quarter_of(r.month) == snap.quarter]
        actuals = monthly_actuals(db, [r.month for r in in_q if r.month in imported])
        published = snap.published_on.isoformat() if snap.published_on else ""
        for r in in_q:
            f_margin = F.net_margin(r.net_profit, r.revenue_cny)
            item = {"month": fmt_month(r.month), "quarter": snap.quarter,
                    "snapshot": f"Q{snap.quarter} 快照" + (f" · {published}" if published else ""),
                    "snapshot_name": snap.name, "forecast_margin": pct(f_margin), "actual_imported": False,
                    "actual_margin": None, "deviation_pp": None, "flagged": False}
            if r.month in actuals:
                a = actuals[r.month]
                a_margin = F.net_margin(a.net_profit, a.revenue)
                dev = F.forecast_deviation_pp(f_margin, a_margin)
                item.update(actual_imported=True, actual_margin=pct(a_margin), deviation_pp=s(dev),
                            flagged=F.forecast_deviation_alert(dev))
            out.append(item)
    out.sort(key=lambda x: x["month"])
    return out


def company_summary(db: Session, ctx: ScopeContext, year: int | None = None) -> dict:
    if not ctx.has_role(*REPORT_VIEW_ROLES["company"]):
        raise Forbidden()
    year = year or default_year(db)
    ach = achievement(db, year)
    if ach is None:
        return {"year": year, "empty": True, "message": f"{year} 年还没有导入金蝶实际"}
    actuals = ach.pop("_actuals")
    last = parse_month(ach["through"])
    return {"year": year, "empty": False, "through": ach["through"], "achievement": ach,
            "growth": growth(db, year, last, actuals), "accuracy": forecast_accuracy(db, year)}


# ---------------------------------------------------------------------------
# API-F10-02 渠道×站点偏差（AC-F10-01~05、AC-F10-12，DEC-024）
# ---------------------------------------------------------------------------
def _ensure_channel_access(ctx: ScopeContext) -> None:
    if not (ctx.all_company or ctx.store_ids or ctx.channel_ids or ctx.customer_ids):
        raise Forbidden()


def _platform_budget(db, ctx, vid: int | None, month: date) -> dict[int, dict]:
    if vid is None:
        return {}
    cols = [PlatformUnit.store_id, func.sum(PlatformUnit.sales_qty), func.sum(PlatformUnit.revenue_local),
            func.sum(PlatformUnit.revenue_cny), func.sum(PlatformUnit.gross_profit)] + \
        [func.sum(getattr(PlatformUnit, k)) for k, _ in COST_ITEMS]
    q = (select(*cols).where(PlatformUnit.version_id == vid, PlatformUnit.month == month,
                             ctx.store_clause(PlatformUnit.store_id, PlatformUnit.channel_id))
         .group_by(PlatformUnit.store_id))
    out = {}
    for row in db.execute(q).all():
        sid, qty, local, rev, gp, *costs = row
        out[sid] = {"qty": qty or ZERO, "local": local or ZERO, "revenue": rev or ZERO, "gross_profit": gp or ZERO,
                    **{k: (v or ZERO) for (k, _), v in zip(COST_ITEMS, costs)}}
    return out


def _b2b_budget(db, ctx, vid: int | None, month: date) -> dict[int, dict]:
    if vid is None:
        return {}
    cols = [B2bUnit.customer_id, func.sum(B2bUnit.sales_local), func.sum(B2bUnit.revenue_cny),
            func.sum(B2bUnit.gross_profit)] + [func.sum(getattr(B2bUnit, k)) for k, _ in COST_ITEMS]
    q = (select(*cols).where(B2bUnit.version_id == vid, B2bUnit.month == month,
                             ctx.customer_clause(B2bUnit.customer_id)).group_by(B2bUnit.customer_id))
    out = {}
    for row in db.execute(q).all():
        cid, local, rev, gp, *costs = row
        out[cid] = {"local": local or ZERO, "revenue": rev or ZERO, "gross_profit": gp or ZERO,
                    **{k: (v or ZERO) for (k, _), v in zip(COST_ITEMS, costs)}}
    return out


def _kingdee_by(db, month: date, key_col, where) -> dict:
    q = (select(key_col, BudgetAccount.pl_item, func.sum(KingdeeActual.amount))
         .join(BudgetAccount, BudgetAccount.id == KingdeeActual.account_id)
         .where(KingdeeActual.batch_id.in_(_effective_batches()), KingdeeActual.month == month,
                BudgetAccount.is_dept_expense.is_(False), BudgetAccount.pl_item.in_(GP_ITEMS), where)
         .group_by(key_col, BudgetAccount.pl_item))
    out: dict = defaultdict(lambda: defaultdict(lambda: ZERO))
    for key, item, amount in db.execute(q).all():
        out[key][item] += amount or ZERO
    return out


def _lines(budget: dict | None, actual: dict | None, with_rates: bool) -> tuple[list[dict], dict]:
    """明细：退款与各项费用的预算 / 实际 / 差额 / 达成率；费率差 =（实际费率 − 预算费率）× 实际人民币收入。"""
    b_rev = budget["revenue"] if budget else ZERO
    a_rev = actual.get("revenue", ZERO) if actual is not None else ZERO
    rows, raw = [], {}
    for key, label in COST_ITEMS:
        b = budget.get(key, ZERO) if budget else ZERO
        a = actual.get(key, ZERO) if actual is not None else ZERO
        b_rate = ratio(b, b_rev)
        a_rate = ratio(a, a_rev)
        rate_diff = F.rate_variance(a, a_rev, b_rate) if (with_rates and b_rate is not None) else None
        raw[key] = (b, a)
        rows.append({"key": key, "label": label, "direction": "higher-better" if key in POSITIVE_ITEMS
                     else "lower-better", "budget": s(b), "actual": s(a), "diff": s(diff(a, b)),
                     "rate": pct(ratio(a, b)), "budget_rate": pct(b_rate) if with_rates else None,
                     "actual_rate": pct(a_rate) if with_rates else None, "rate_diff": s(rate_diff)})
    return rows, raw


def _metric(b: Decimal | None, a: Decimal | None) -> dict:
    return {"budget": s(b), "actual": s(a), "diff": s(diff(a, b)), "rate": pct(ratio(a, b))}


def _margin(b_gp, b_rev, a_gp, a_rev) -> dict:
    bm, am = ratio(b_gp, b_rev), ratio(a_gp, a_rev)
    d = (am - bm) * HUNDRED if bm is not None and am is not None else None
    return {"budget": pct(bm), "actual": pct(am), "diff_pp": s(d)}


def channel_site(db: Session, ctx: ScopeContext, month: str | None = None, baseline: str = "adj",
                 channel: str | None = None) -> dict:
    _ensure_channel_access(ctx)
    if baseline not in BASELINES:
        raise ValidationFailed("对比基准不合法", details={"baseline": baseline})
    kd_months = kingdee_months(db)
    months = [fmt_month(m) for m in reversed(kd_months)]
    bi_ms = bi_months(db)
    bi_latest = fmt_month(bi_ms[-1]) if bi_ms else None
    base = {"months": months, "baseline": baseline,
            "baseline_options": [{"value": k, "label": v} for k, v in BASELINES.items()],
            "bi_latest": bi_latest, "can_edit_note": ctx.has_role(Role.FINANCE_BP)}
    if month is None:
        if not kd_months:
            return {**base, "month": None, "empty": True, "message": "还没有金蝶实际"}
        m = kd_months[-1]
    else:
        try:
            m = parse_month(month)
        except ValueError as e:
            raise ValidationFailed(str(e)) from e
    base["month"] = fmt_month(m)
    if m not in kd_months:
        return {**base, "empty": True, "message": f"{fmt_month(m)} 还没有金蝶实际"}

    version, base_label = resolve_baseline(db, m.year, baseline)
    vid = data_version_id(db, version) if version else None
    bi_available = m in bi_ms
    bfx, afx = budget_fx(db, m.year), actual_fx(db, m)

    # 维度：范围内的店铺、渠道、客户
    stores = {st.id: (st, ch, site) for st, ch, site in db.execute(
        select(Store, Channel, Site).join(Channel, Channel.id == Store.channel_id).join(Site, Site.id == Store.site_id)
        .where(ctx.store_clause(Store.id, Store.channel_id)).order_by(Channel.sort, Store.id)).all()}
    customers = {c.id: (c, d) for c, d in db.execute(
        select(BCustomer, Department).join(Department, Department.id == BCustomer.department_id)
        .where(ctx.customer_clause(BCustomer.id)).order_by(BCustomer.id)).all()}
    channels_seen: dict[int, str] = {}
    for st, ch, _ in stores.values():
        channels_seen.setdefault(ch.id, ch.name)
    channel_options = [{"value": "all", "label": "全部"}] + \
        [{"value": str(cid), "label": name} for cid, name in channels_seen.items()]
    if customers:
        channel_options.append({"value": "b2b", "label": "B 端"})
    ch_filter = channel or "all"
    if ch_filter not in {o["value"] for o in channel_options}:
        raise ValidationFailed("渠道不在你的数据范围内")

    p_budget = _platform_budget(db, ctx, vid, m)
    kd_store = _kingdee_by(db, m, KingdeeActual.store_id, and_(KingdeeActual.store_id.is_not(None),
                                                               KingdeeActual.store_id.in_(list(stores) or [0])))
    bi = {}
    if bi_available:
        q = (select(BiActualAgg.store_id, func.sum(BiActualAgg.qty), func.sum(BiActualAgg.revenue_local))
             .where(BiActualAgg.batch_id.in_(_effective_batches()), BiActualAgg.month == m,
                    BiActualAgg.store_id.in_(list(stores) or [0]))
             .group_by(BiActualAgg.store_id))
        bi = {sid: (qty or ZERO, local or ZERO) for sid, qty, local in db.execute(q).all()}
    notes = load_notes(db, "channel-site", m)

    rows: list[dict] = []
    total = {"b_rev": ZERO, "a_rev": ZERO, "b_gp": ZERO, "a_gp": ZERO, "vol": ZERO, "price": ZERO, "fx": ZERO,
             "basis": ZERO, "fx_missing": False, "split": False, "lines": defaultdict(lambda: [ZERO, ZERO])}

    def add_lines(raw):
        for k, (b, a) in raw.items():
            total["lines"][k][0] += b or ZERO
            total["lines"][k][1] += a or ZERO

    if ch_filter != "b2b":
        for sid, (st, ch, site) in stores.items():
            if ch_filter != "all" and str(ch.id) != ch_filter:
                continue
            b = p_budget.get(sid)
            a = kd_store.get(sid)
            if b is None and a is None and sid not in bi:
                continue
            b = b or {"qty": ZERO, "local": ZERO, "revenue": ZERO, "gross_profit": ZERO,
                      **{k: ZERO for k, _ in COST_ITEMS}}
            a = dict(a) if a is not None else {}
            a_rev = a.get("revenue", ZERO)
            a_gp = gross_profit_of(a)
            lines, raw = _lines(b, a, bi_available)
            split = None
            local_actual = None
            if bi_available:
                aq, alocal = bi.get(sid, (ZERO, ZERO))
                local_actual = alocal
                b_fx, a_fx = bfx.get(st.currency), afx.get(st.currency)
                if b["qty"] > 0 and b_fx is not None:
                    b_net = b["local"] / b["qty"]
                    sp = F.revenue_variance_split(budget_qty=b["qty"], budget_avg_price=b_net,
                                                  budget_discount_rate=ZERO, budget_fx=b_fx, actual_qty=aq,
                                                  actual_revenue_local=alocal, actual_fx=a_fx,
                                                  kingdee_revenue_cny=a_rev)
                    split = {"volume": s(sp.volume), "price": s(sp.price), "fx": s(sp.fx), "basis": s(sp.basis),
                             "total": s(a_rev - b["revenue"]), "missing_fx": sp.missing_fx,
                             "missing_fx_text": f"缺少 {fmt_month(m)} 汇率" if sp.missing_fx else None,
                             "budget_qty": s(b["qty"]), "budget_net_price": s(b_net), "actual_qty": s(aq),
                             "actual_net_price": s(ratio(alocal, aq)), "budget_fx": s(b_fx), "actual_fx": s(a_fx)}
                    total["split"] = True
                    total["vol"] += sp.volume
                    total["price"] += sp.price
                    if sp.missing_fx:
                        total["fx_missing"] = True
                    else:
                        total["fx"] += sp.fx
                        total["basis"] += sp.basis
            key = str(sid)
            rows.append({
                "kind": "store", "key": f"store:{sid}", "note_key": {"object_type": "store", "object_key": key},
                "name": st.name, "channel": ch.name, "site": site.name, "currency": st.currency,
                "is_new_channel": st.is_new_channel, "revenue": _metric(b["revenue"], a_rev),
                "revenue_local_budget": s(b["local"]), "revenue_local_actual": s(local_actual),
                "split": split, "gross_profit": _metric(b["gross_profit"], a_gp),
                "gross_margin": _margin(b["gross_profit"], b["revenue"], a_gp, a_rev), "lines": lines,
                "note": notes.get(("store", key)),
            })
            total["b_rev"] += b["revenue"]
            total["a_rev"] += a_rev
            total["b_gp"] += b["gross_profit"]
            total["a_gp"] += a_gp
            add_lines(raw)

    b2b_rows = []
    if ch_filter in ("all", "b2b") and customers:
        bb = _b2b_budget(db, ctx, vid, m)
        kd_c = _kingdee_by(db, m, KingdeeActual.customer_id,
                           KingdeeActual.customer_id.in_(list(customers)))
        for cid, (c, d) in customers.items():
            b, a = bb.get(cid), kd_c.get(cid)
            if b is None and a is None:
                continue
            b = b or {"local": ZERO, "revenue": ZERO, "gross_profit": ZERO, **{k: ZERO for k, _ in COST_ITEMS}}
            a = dict(a) if a is not None else {}
            a_rev, a_gp = a.get("revenue", ZERO), gross_profit_of(a)
            lines, raw = _lines(b, a, True)
            key = str(cid)
            b2b_rows.append({
                "kind": "b2b", "key": f"customer:{cid}", "note_key": {"object_type": "customer", "object_key": key},
                "name": c.name, "channel": f"B 端 · {d.name}", "site": None, "currency": c.currency,
                "department": d.name, "is_new_channel": False, "revenue": _metric(b["revenue"], a_rev),
                "revenue_local_budget": s(b["local"]), "revenue_local_actual": None, "split": None,
                "gross_profit": _metric(b["gross_profit"], a_gp),
                "gross_margin": _margin(b["gross_profit"], b["revenue"], a_gp, a_rev), "lines": lines,
                "note": notes.get(("customer", key)),
            })
            total["b_rev"] += b["revenue"]
            total["a_rev"] += a_rev
            total["b_gp"] += b["gross_profit"]
            total["a_gp"] += a_gp
            add_lines(raw)

    unassigned = None
    if ctx.all_company and ch_filter == "all":
        kd_u = _kingdee_by(db, m, KingdeeActual.unassigned, KingdeeActual.unassigned.is_(True))
        a = kd_u.get(True)
        if a:
            a = dict(a)
            a_gp = gross_profit_of(a)
            lines = [{"key": k, "label": label, "direction": "higher-better" if k in POSITIVE_ITEMS
                      else "lower-better", "budget": None, "actual": s(a.get(k, ZERO)), "diff": None, "rate": None,
                      "budget_rate": None, "actual_rate": None, "rate_diff": None}
                     for k, label in COST_ITEMS if a.get(k)]
            unassigned = {"kind": "unassigned", "key": "unassigned",
                          "note_key": {"object_type": "unassigned", "object_key": "unassigned"},
                          "name": "未归属渠道", "channel": None, "site": None, "currency": None,
                          "is_new_channel": False, "revenue": {"budget": None, "actual": None, "diff": None,
                                                               "rate": None},
                          "revenue_local_budget": None, "revenue_local_actual": None, "split": None,
                          "gross_profit": {"budget": None, "actual": s(a_gp), "diff": None, "rate": None},
                          "gross_margin": {"budget": None, "actual": None, "diff_pp": None}, "lines": lines,
                          "note": notes.get(("unassigned", "unassigned"))}
            total["a_gp"] += a_gp
            for k, _ in COST_ITEMS:
                total["lines"][k][1] += a.get(k, ZERO)

    total_label = "合计（含 B 端与未归属渠道）" if ctx.all_company and ch_filter == "all" else "合计（当前范围）"
    split_total = None
    if bi_available and total["split"]:
        split_total = {"volume": s(total["vol"]), "price": s(total["price"]),
                       "fx": None if total["fx_missing"] else s(total["fx"]),
                       "basis": None if total["fx_missing"] else s(total["basis"]),
                       "missing_fx": total["fx_missing"],
                       "missing_fx_text": f"缺少 {fmt_month(m)} 汇率" if total["fx_missing"] else None}
    return {
        **base, "empty": False, "year": m.year, "baseline_label": base_label,
        "baseline_version": version_brief(version), "channel": ch_filter, "channel_options": channel_options,
        "bi_available": bi_available,
        "bi_notice": None if bi_available else f"量价拆分待 BI 数据（最近 BI 数据截至 {bi_latest or '—'}）",
        "fx": {"budget": {k: s(v) for k, v in sorted(bfx.items())},
               "actual": {k: s(afx.get(k)) for k in sorted(bfx)}},
        "rows": rows, "b2b_rows": b2b_rows, "unassigned": unassigned,
        "total": {"label": total_label, "revenue": _metric(total["b_rev"], total["a_rev"]), "split": split_total,
                  "gross_profit": _metric(total["b_gp"], total["a_gp"]),
                  "gross_margin": _margin(total["b_gp"], total["b_rev"], total["a_gp"], total["a_rev"])},
    }


# ---------------------------------------------------------------------------
# API-F10-03 品类×新老品偏差（AC-F10-06，DEC-025）
# ---------------------------------------------------------------------------
def _ensure_store_access(ctx: ScopeContext) -> None:
    if not (ctx.all_company or ctx.store_ids or ctx.channel_ids):
        raise Forbidden()


def category_report(db: Session, ctx: ScopeContext, month: str | None = None) -> dict:
    _ensure_store_access(ctx)
    bi_ms = bi_months(db)
    months = [fmt_month(m) for m in reversed(bi_ms)]
    base = {"months": months, "bi_latest": months[0] if months else None,
            "can_edit_note": ctx.has_role(Role.FINANCE_BP)}
    if month is None:
        if not bi_ms:
            return {**base, "month": None, "empty": True, "message": f"{default_year(db)} 年还没有导入 BI 数据"}
        m = bi_ms[-1]
    else:
        try:
            m = parse_month(month)
        except ValueError as e:
            raise ValidationFailed(str(e)) from e
    base["month"] = fmt_month(m)
    if m not in bi_ms:
        return {**base, "empty": True, "message": f"{fmt_month(m)} 还没有 BI 实际，只能选择已有 BI 实际的月份"}

    version, fell_back = target_version(db, m.year)
    vid = data_version_id(db, version) if version else None
    afx = actual_fx(db, m)
    budget: dict[tuple[int, bool], list] = defaultdict(lambda: [0, ZERO, ZERO])  # spu, qty, rev_cny
    if vid is not None:
        q = (select(PlatformUnit.category_id, PlatformUnit.is_new, func.sum(PlatformUnit.spu_count),
                    func.sum(PlatformUnit.sales_qty), func.sum(PlatformUnit.revenue_cny))
             .where(PlatformUnit.version_id == vid, PlatformUnit.month == m,
                    ctx.store_clause(PlatformUnit.store_id, PlatformUnit.channel_id))
             .group_by(PlatformUnit.category_id, PlatformUnit.is_new))
        for cat, is_new, spu, qty, rev in db.execute(q).all():
            budget[(cat, is_new)] = [int(spu or 0), qty or ZERO, rev or ZERO]
    actual: dict[tuple[int, bool], list] = defaultdict(lambda: [0, ZERO, ZERO, False])  # spu, qty, rev_cny, missing
    q = (select(BiActualAgg).join(Store, Store.id == BiActualAgg.store_id)
         .where(BiActualAgg.batch_id.in_(_effective_batches()), BiActualAgg.month == m,
                ctx.store_clause(BiActualAgg.store_id, Store.channel_id)))
    for agg in db.scalars(q).all():
        a = actual[(agg.category_id, agg.is_new)]
        a[0] += agg.spu_count
        a[1] += agg.qty
        cny = agg.revenue_cny
        if cny is None:
            fx = afx.get(agg.currency)
            cny = agg.revenue_local * fx if fx is not None else None
        if cny is None:
            a[3] = True
        else:
            a[2] += cny
    notes = load_notes(db, "category", m)
    cats = db.scalars(select(Category).order_by(Category.sort, Category.id)).all()

    def row(label_cat, label_kind, b, a, note_key=None):
        b_spu, b_qty, b_rev = b
        a_spu, a_qty, a_rev, missing = a
        a_rev_v = None if missing else a_rev
        b_eff = ratio(b_rev, Decimal(b_spu)) if b_spu else None
        a_eff = ratio(a_rev_v, Decimal(a_spu)) if (a_spu and a_rev_v is not None) else None
        eff_diff = diff(a_eff, b_eff) if b_eff is not None else a_eff
        out = {"category": label_cat, "kind": label_kind,
               "spu": {"budget": str(b_spu), "actual": str(a_spu), "diff": str(a_spu - b_spu)},
               "qty": {"budget": s(b_qty), "actual": s(a_qty), "diff": s(a_qty - b_qty)},
               "efficiency": {"budget": s(b_eff), "actual": s(a_eff), "diff": s(eff_diff)},
               "revenue": {"budget": s(b_rev), "actual": s(a_rev_v), "diff": s(diff(a_rev_v, b_rev))},
               "missing_fx": missing}
        if note_key:
            out["note_key"] = {"object_type": "category", "object_key": note_key}
            out["note"] = notes.get(("category", note_key))
        return out

    def add(acc_b, acc_a, b, a):
        acc_b[0] += b[0]; acc_b[1] += b[1]; acc_b[2] += b[2]  # noqa: E702
        acc_a[0] += a[0]; acc_a[1] += a[1]; acc_a[2] += a[2]; acc_a[3] = acc_a[3] or a[3]  # noqa: E702

    groups, tb, ta = [], [0, ZERO, ZERO], [0, ZERO, ZERO, False]
    for c in cats:
        sb, sa, items = [0, ZERO, ZERO], [0, ZERO, ZERO, False], []
        for is_new, label in ((True, "新品"), (False, "老品")):
            b, a = budget[(c.id, is_new)], actual[(c.id, is_new)]
            items.append(row(c.name, label, b, a, f"{c.id}:{'new' if is_new else 'old'}"))
            add(sb, sa, b, a)
        add(tb, ta, sb, sa)
        groups.append({"category": c.name, "rows": items, "subtotal": row(c.name, "小计", sb, sa)})
    return {**base, "empty": False, "year": m.year,
            "baseline_label": (f"{version.name}（本年度暂无调整，取年初原始目标）" if fell_back else version.name)
            if version else "尚无年初原始目标",
            "scope_label": "全部渠道" if ctx.all_company else "我负责的渠道",
            "fx": {k: s(v) for k, v in sorted(afx.items())},
            "groups": groups, "total": row("合计", "品效按人民币汇总", tb, ta)}


# ---------------------------------------------------------------------------
# API-F10-04 部门费用报告（AC-F10-07）
# ---------------------------------------------------------------------------
def _ensure_dept_access(ctx: ScopeContext) -> None:
    if not (ctx.all_company or ctx.department_ids):
        raise Forbidden()


def dept_report(db: Session, ctx: ScopeContext, year: int | None = None, department_id: int | None = None) -> dict:
    _ensure_dept_access(ctx)
    year = year or default_year(db)
    if department_id is not None:
        ctx.ensure_department(department_id)
    depts = db.scalars(select(Department).where(ctx.department_clause(Department.id))
                       .order_by(Department.sort, Department.id)).all()
    base = {"year": year, "departments": [{"id": d.id, "name": d.name} for d in depts],
            "department_id": department_id, "can_edit_note": ctx.has_role(Role.FINANCE_BP)}
    last = latest_kingdee_month(db, year)
    if last is None:
        return {**base, "empty": True, "message": f"{year} 年还没有导入金蝶实际"}
    version, fell_back = target_version(db, year)
    vid = data_version_id(db, version) if version else None
    dept_ids = [d.id for d in depts if department_id is None or d.id == department_id]
    budget: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    if vid is not None:
        q = (select(DeptExpense.department_id, DeptExpense.account_id, func.sum(DeptExpense.amount))
             .where(DeptExpense.version_id == vid, func.extract("year", DeptExpense.month) == year,
                    DeptExpense.department_id.in_(dept_ids))
             .group_by(DeptExpense.department_id, DeptExpense.account_id))
        for d, acc, v in db.execute(q).all():
            budget[(d, acc)] += v or ZERO
        q = (select(Reserve.department_id, Reserve.account_id, func.sum(Reserve.amount))
             .where(Reserve.version_id == vid, func.extract("year", Reserve.plan_month) == year,
                    Reserve.department_id.in_(dept_ids))
             .group_by(Reserve.department_id, Reserve.account_id))
        for d, acc, v in db.execute(q).all():
            budget[(d, acc)] += v or ZERO
    actual: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    q = (select(KingdeeActual.department_id, KingdeeActual.account_id, func.sum(KingdeeActual.amount))
         .join(BudgetAccount, BudgetAccount.id == KingdeeActual.account_id)
         .where(KingdeeActual.batch_id.in_(_effective_batches()), BudgetAccount.is_dept_expense.is_(True),
                KingdeeActual.month >= date(year, 1, 1), KingdeeActual.month <= last,
                KingdeeActual.department_id.in_(dept_ids))
         .group_by(KingdeeActual.department_id, KingdeeActual.account_id))
    for d, acc, v in db.execute(q).all():
        actual[(d, acc)] += v or ZERO
    accounts = {a.id: a for a in db.scalars(select(BudgetAccount)).all()}
    progress = F.time_progress(last.month)
    notes = load_notes(db, "dept-expense", last)

    def metric(b, a):
        return {"budget": s(b), "actual": s(a), "usage": pct(F.quota_usage(a, b))}

    groups, tb, ta = [], ZERO, ZERO
    for d in depts:
        if d.id not in dept_ids:
            continue
        keys = sorted({acc for (dd, acc) in list(budget) + list(actual) if dd == d.id},
                      key=lambda acc: (accounts[acc].sort, acc))
        if not keys:
            continue
        items, sb, sa = [], ZERO, ZERO
        for acc in keys:
            b, a = budget[(d.id, acc)], actual[(d.id, acc)]
            nk = f"{d.id}:{acc}"
            items.append({"department": d.name, "account": accounts[acc].name, **metric(b, a),
                          "note_key": {"object_type": "dept-account", "object_key": nk},
                          "note": notes.get(("dept-account", nk))})
            sb += b
            sa += a
        groups.append({"department_id": d.id, "department": d.name, "rows": items,
                       "subtotal": {"department": d.name, "account": "部门合计", **metric(sb, sa)}})
        tb += sb
        ta += sa
    total_label = "全公司合计" if ctx.all_company and department_id is None else (
        "合计（我的部门）" if not ctx.all_company else "合计（当前部门）")
    return {**base, "empty": False, "through": fmt_month(last), "imported_months": last.month,
            "time_progress": pct(progress),
            "baseline_label": (f"{version.name}（本年度暂无调整，取年初原始目标）" if fell_back else version.name)
            if version else "尚无年初原始目标",
            "groups": groups, "total": {"department": total_label, "account": "", **metric(tb, ta)}}


__all__ = ["company_summary", "channel_site", "category_report", "dept_report", "save_note", "achievement",
           "forecast_accuracy", "kingdee_months", "bi_months", "latest_kingdee_month", "default_year", "COST_ITEMS"]
