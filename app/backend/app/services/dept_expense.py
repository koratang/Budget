"""部门费用与专项预留额度（REQ-F05-01/02、AC-F05-01~05；API-F05-01/02；PAGE-F05-01/02）。

- 表格：预算科目 × 月的人民币金额（保存复用 API-F04-03，行 key「de:<科目>|amount」）；同一科目给出上年同月实际与
  最近 12 个已导入月份实际合计，无历史显示「无历史数据」（AC-F05-02）。
- 专项：计入该部门该科目计划月份的预算（AC-F05-03）；列表给出所属科目上一年全年实际（AC-F05-04）；
  财务BP 登记使用后已用、剩余 = 预留 − 已用（AC-F05-05，超支允许，剩余为负）。
历史实际 = 已生效（未被替换）的金蝶导入批次中该部门该科目的金额。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calc.formulas import prior_year_same_month, recent_12_months_total
from app.calc.periods import fmt_month, parse_month, year_months
from app.core.audit import write_audit
from app.core.auth import CurrentUser
from app.core.clock import clock
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.money import MoneyError, fmt_amount, fmt_cny, to_decimal
from app.core.scope import ScopeContext
from app.models import (BudgetAccount, BudgetVersion, Department, DeptExpense, FillingUnit, ImportBatch,
                        KingdeeActual, Reserve, ReserveUsage)
from app.models.enums import ImportSource, ImportStatus, Role, UnitType
from app.services import filling as F
from app.services import tasking as T

ZERO = Decimal(0)
NO_HISTORY = "无历史数据"
NOT_IMPORTED = "未导入"
KINGDEE_SOURCES = (ImportSource.KINGDEE, ImportSource.KINGDEE_HISTORY, ImportSource.OPS_HISTORY)


# ---------------------------------------------------------------------------
# 历史实际（AC-F05-02、AC-F05-04）
# ---------------------------------------------------------------------------
def _effective_actuals():
    return (select(KingdeeActual).join(ImportBatch, ImportBatch.id == KingdeeActual.batch_id)
            .where(ImportBatch.status == ImportStatus.EFFECTIVE, ImportBatch.source.in_(KINGDEE_SOURCES)))


def imported_months(db: Session) -> set[date]:
    """已导入的金蝶月份：已生效批次的期间 ∪ 已生效批次中出现的实际月份。"""
    periods = set(db.scalars(select(ImportBatch.period).where(ImportBatch.status == ImportStatus.EFFECTIVE,
                                                              ImportBatch.source.in_(KINGDEE_SOURCES),
                                                              ImportBatch.period.is_not(None)).distinct()))
    months = set(db.scalars(select(KingdeeActual.month).join(ImportBatch, ImportBatch.id == KingdeeActual.batch_id)
                            .where(ImportBatch.status == ImportStatus.EFFECTIVE,
                                   ImportBatch.source.in_(KINGDEE_SOURCES)).distinct()))
    return periods | months


def dept_actuals(db: Session, department_id: int) -> dict[int, dict[date, Decimal]]:
    """科目 → {月份: 实际合计}。"""
    rows = db.execute(select(KingdeeActual.account_id, KingdeeActual.month, func.sum(KingdeeActual.amount))
                      .join(ImportBatch, ImportBatch.id == KingdeeActual.batch_id)
                      .where(ImportBatch.status == ImportStatus.EFFECTIVE, ImportBatch.source.in_(KINGDEE_SOURCES),
                             KingdeeActual.department_id == department_id)
                      .group_by(KingdeeActual.account_id, KingdeeActual.month)).all()
    out: dict[int, dict[date, Decimal]] = defaultdict(dict)
    for acc, month, amount in rows:
        out[acc][month] = amount
    return out


def prior_year_label(db: Session, year: int) -> str:
    """专项列「上年同科目实际」的列名：上一年全部 12 个月已导入时为全年，否则注明已导入区间与未导入月份。"""
    prev = year - 1
    months = sorted(m for m in imported_months(db) if m.year == prev)
    if len(months) == 12:
        return f"上年同科目全年实际（{prev}）"
    if not months:
        return f"上年同科目实际（{prev} 年未导入）"
    missing = [str(m.month) for m in year_months(prev) if m not in months]
    return (f"上年同科目实际（{fmt_month(months[0])}～{months[-1].month:02d}，"
            f"{'、'.join(missing)} 月未导入）")


def prior_year_total(actuals: dict[date, Decimal], year: int, imported: set[date]) -> Decimal | None:
    months = [m for m in year_months(year - 1) if m in imported]
    if not any(m in actuals for m in months):
        return None
    return sum((actuals.get(m, ZERO) for m in months), ZERO)


# ---------------------------------------------------------------------------
# 表格（API-F05-01）
# ---------------------------------------------------------------------------
def _ensure_dept_reader(ctx: ScopeContext, department_id: int) -> None:
    if ctx.all_company:
        return
    if ctx.has_role(Role.DEPT_BUDGET, Role.DEPT_HEAD) and department_id in ctx.department_ids:
        return
    raise Forbidden()


def dept_grid(db: Session, ctx: ScopeContext, unit: FillingUnit) -> dict:
    version = db.get(BudgetVersion, unit.version_id)
    dept = db.get(Department, unit.scope_object_id)
    writable = F._can_write(db, ctx, unit)
    months = year_months(version.year)
    keys = [fmt_month(m) for m in months]
    data = list(db.scalars(select(DeptExpense).where(DeptExpense.version_id == version.id,
                                                      DeptExpense.department_id == dept.id)))
    by_acc: dict[int, dict[date, DeptExpense]] = defaultdict(dict)
    for r in data:
        by_acc[r.account_id][r.month] = r
    accounts = list(db.scalars(select(BudgetAccount).where(BudgetAccount.id.in_(by_acc))
                               .order_by(BudgetAccount.sort, BudgetAccount.id)))
    reserves = list(db.scalars(select(Reserve).where(Reserve.version_id == version.id,
                                                     Reserve.department_id == dept.id)))
    res_by: dict[int, dict[date, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for r in reserves:
        res_by[r.account_id][r.plan_month] += r.amount
    actuals = dept_actuals(db, dept.id)
    imported = imported_months(db)
    rows: list[dict] = []
    recent_sum = ZERO
    for acc in accounts:
        cells = by_acc[acc.id]
        act = actuals.get(acc.id, {})
        recent = recent_12_months_total(act, imported)
        if recent is not None:
            recent_sum += recent
        has_res = acc.id in res_by
        dims = {"account": acc.name}
        rows.append({"key": f"de:{acc.id}|amount", "kind": "input",
                     "values": {**dims, "item": "日常预算" if has_res else "预算",
                                **{fmt_month(m): F.fmt_input("money2", r.amount) for m, r in cells.items()},
                                "year_total": fmt_amount(sum((r.amount for r in cells.values()), ZERO)),
                                "recent12": fmt_amount(recent) if recent is not None else NO_HISTORY}})
        if has_res:
            res = res_by[acc.id]
            rows.append({"key": f"de:{acc.id}|reserve", "kind": "calc",
                         "values": {**dims, "item": "专项预留",
                                    **{k: fmt_amount(res[m]) if m in res else "—" for k, m in zip(keys, months)},
                                    "year_total": fmt_amount(sum(res.values(), ZERO)), "recent12": None}})
            rows.append({"key": f"de:{acc.id}|subtotal", "kind": "calc",
                         "values": {**dims, "item": "科目预算合计",
                                    **{k: fmt_amount((cells[m].amount if m in cells else ZERO) + res.get(m, ZERO))
                                       for k, m in zip(keys, months)},
                                    "year_total": fmt_amount(sum((r.amount for r in cells.values()), ZERO)
                                                             + sum(res.values(), ZERO)),
                                    "recent12": None}})
        if recent is None:
            rows.append({"key": f"de:{acc.id}|prior", "kind": "calc",
                         "values": {**dims, "item": NO_HISTORY, "recent12": None}})
        else:
            prior = {}
            for k, m in zip(keys, months):
                prev = m.replace(year=m.year - 1)
                prior[k] = fmt_amount(prior_year_same_month(act, m) or ZERO) if prev in imported else NOT_IMPORTED
            rows.append({"key": f"de:{acc.id}|prior", "kind": "calc",
                         "values": {**dims, "item": "上年同月实际", **prior, "recent12": None}})
    # 部门合计：SQL SUM（日常 + 专项）
    agg = dict(db.execute(select(DeptExpense.month, func.sum(DeptExpense.amount))
                          .where(DeptExpense.version_id == version.id, DeptExpense.department_id == dept.id)
                          .group_by(DeptExpense.month)).all())
    ragg = dict(db.execute(select(Reserve.plan_month, func.sum(Reserve.amount))
                           .where(Reserve.version_id == version.id, Reserve.department_id == dept.id)
                           .group_by(Reserve.plan_month)).all())
    month_tot = {m: (agg.get(m) or ZERO) + (ragg.get(m) or ZERO) for m in months}
    year_tot = sum(month_tot.values(), ZERO)
    reserve_tot = sum((r.amount for r in reserves), ZERO)
    rows.append({"key": "total|budget", "kind": "total",
                 "values": {"account": "部门合计", "item": "预算合计（含专项）",
                            **{k: fmt_amount(month_tot[m]) for k, m in zip(keys, months)},
                            "year_total": fmt_amount(year_tot), "recent12": fmt_amount(recent_sum)}})
    prior_tot = {}
    for k, m in zip(keys, months):
        prev = m.replace(year=m.year - 1)
        prior_tot[k] = fmt_amount(sum((a.get(prev, ZERO) for a in actuals.values()), ZERO)) \
            if prev in imported else NOT_IMPORTED
    rows.append({"key": "total|prior", "kind": "total",
                 "values": {"account": "部门合计", "item": "上年同月实际合计", **prior_tot, "recent12": None}})
    columns = [F._dim("account", "预算科目", 120), F._dim("item", "项目", 130),
               *F._month_cols(version.year, writable),
               {"key": "recent12", "label": "近 12 月实际合计", "kind": "value", "type": "number",
                "editable": False, "width": 140}]
    return {
        "unit": T.unit_info(db, ctx, unit),
        "department": {"id": dept.id, "name": dept.name},
        "columns": columns,
        "rows": rows,
        "flags": {},
        "kpis": {
            "year_total_display": fmt_cny(year_tot),
            "reserve_total_display": fmt_cny(reserve_tot),
            "reserve_count": len(reserves),
            "recent12_display": fmt_cny(recent_sum),
        },
    }


def my_dept_unit(db: Session, ctx: ScopeContext) -> dict | None:
    """部门费用入口（不带 unitId）：本人可填报或可查看的最近一个部门费用单位。"""
    units = db.scalars(select(FillingUnit).where(FillingUnit.unit_type == UnitType.DEPT_EXPENSE)
                       .order_by(FillingUnit.id.desc()))
    for u in units:
        if T.can_fill(db, ctx, u):
            return {"unit_id": u.id}
    if ctx.has_role(Role.DEPT_HEAD):
        for u in db.scalars(select(FillingUnit).where(FillingUnit.unit_type == UnitType.DEPT_EXPENSE,
                                                      FillingUnit.scope_object_id.in_(ctx.department_ids))
                            .order_by(FillingUnit.id.desc())):
            return {"unit_id": u.id}
    return None


# ---------------------------------------------------------------------------
# 专项预留额度（API-F05-02）
# ---------------------------------------------------------------------------
def _latest_dept_unit(db: Session, department_id: int) -> FillingUnit | None:
    return db.scalar(select(FillingUnit).where(FillingUnit.unit_type == UnitType.DEPT_EXPENSE,
                                               FillingUnit.scope_object_id == department_id,
                                               FillingUnit.task_id.is_not(None))
                     .order_by(FillingUnit.id.desc()).limit(1))


def _money(raw, *, required: str, invalid: str = "金额须大于 0，最多 2 位小数") -> Decimal:
    if raw is None or str(raw).strip() == "":
        raise ValidationFailed(required, code="required")
    try:
        d = to_decimal(str(raw))
    except MoneyError:
        raise ValidationFailed(invalid, code="invalid_amount") from None
    if d <= 0 or F._places(d) > 2:
        raise ValidationFailed(invalid, code="invalid_amount")
    return d


def reserve_view(db: Session, r: Reserve, actuals: dict[int, dict[date, Decimal]], imported: set[date],
                 year: int) -> dict:
    usages = list(db.scalars(select(ReserveUsage).where(ReserveUsage.reserve_id == r.id)
                             .order_by(ReserveUsage.used_on, ReserveUsage.id)))
    used = sum((u.amount for u in usages), ZERO)
    remaining = r.amount - used
    prior = prior_year_total(actuals.get(r.account_id, {}), year, imported)
    return {
        "id": r.id, "name": r.name, "account_id": r.account_id,
        "account": db.scalar(select(BudgetAccount.name).where(BudgetAccount.id == r.account_id)),
        "plan_month": fmt_month(r.plan_month),
        "amount": str(r.amount), "amount_display": fmt_amount(r.amount),
        "used": str(used), "used_display": fmt_amount(used),
        "remaining": str(remaining), "remaining_display": fmt_amount(remaining),
        "prior_year_actual": str(prior) if prior is not None else None,
        "prior_year_actual_display": fmt_amount(prior) if prior is not None else NO_HISTORY,
        "usages": [{"id": u.id, "amount": str(u.amount), "amount_display": fmt_amount(u.amount),
                    "used_on": u.used_on.isoformat(), "voucher_no": u.voucher_no} for u in usages],
    }


def list_reserves(db: Session, ctx: ScopeContext, department_id: int | None) -> dict:
    if department_id is None:
        if ctx.department_ids:
            department_id = sorted(ctx.department_ids)[0]
        else:
            first = db.scalar(select(FillingUnit.scope_object_id).where(
                FillingUnit.unit_type == UnitType.DEPT_EXPENSE).order_by(FillingUnit.id.desc()).limit(1))
            if first is None:
                raise NotFound("暂无部门费用填报单位")
            department_id = first
    _ensure_dept_reader(ctx, department_id)
    dept = db.get(Department, department_id)
    if dept is None:
        raise NotFound("部门不存在")
    unit = _latest_dept_unit(db, department_id)
    if unit is None:
        return {"department": {"id": dept.id, "name": dept.name}, "unit": None, "reserves": [], "accounts": [],
                "departments": _dept_options(db, ctx), "can_create": False, "can_register": False,
                "prior_label": None, "totals": None}
    version = db.get(BudgetVersion, unit.version_id)
    actuals = dept_actuals(db, department_id)
    imported = imported_months(db)
    reserves = list(db.scalars(select(Reserve).where(Reserve.version_id == unit.version_id,
                                                     Reserve.department_id == department_id)
                               .order_by(Reserve.plan_month, Reserve.id)))
    views = [reserve_view(db, r, actuals, imported, version.year) for r in reserves]
    tot_amount = sum((Decimal(v["amount"]) for v in views), ZERO)
    tot_used = sum((Decimal(v["used"]) for v in views), ZERO)
    accounts = list(db.scalars(select(BudgetAccount).where(BudgetAccount.is_dept_expense, BudgetAccount.is_active)
                               .order_by(BudgetAccount.sort, BudgetAccount.id)))
    prev_months = [m for m in year_months(version.year - 1) if m in imported]
    acc_opts = []
    for a in accounts:
        p = prior_year_total(actuals.get(a.id, {}), version.year, imported)
        acc_opts.append({"id": a.id, "name": a.name, "prior_year_actual_display": fmt_cny(p) if p is not None
                         else NO_HISTORY})
    return {
        "department": {"id": dept.id, "name": dept.name},
        "unit": T.unit_info(db, ctx, unit),
        "year": version.year,
        "reserves": views,
        "accounts": acc_opts,
        "prior_range": (f"{fmt_month(prev_months[0])}～{prev_months[-1].month:02d}" if prev_months else None),
        "prior_label": prior_year_label(db, version.year),
        "departments": _dept_options(db, ctx),
        "can_create": F._can_write(db, ctx, unit),
        "can_register": ctx.has_role(Role.FINANCE_BP),
        "totals": {"amount_display": fmt_amount(tot_amount), "used_display": fmt_amount(tot_used),
                   "remaining": str(tot_amount - tot_used), "remaining_display": fmt_amount(tot_amount - tot_used)},
    }


def _dept_options(db: Session, ctx: ScopeContext) -> list[dict]:
    ids = set(db.scalars(select(FillingUnit.scope_object_id).where(FillingUnit.unit_type == UnitType.DEPT_EXPENSE)))
    if not ctx.all_company:
        ids &= set(ctx.department_ids)
    return [{"id": d.id, "name": d.name} for d in db.scalars(select(Department).where(Department.id.in_(ids))
                                                             .order_by(Department.sort, Department.id))]


def create_reserve(db: Session, ctx: ScopeContext, actor: CurrentUser, body: dict, request=None) -> dict:
    """AC-F05-03：新增专项 → 计入该部门该科目计划月份预算（部门费用单位已提交时不能新增，DEC-F05-03）。"""
    department_id = body.get("department_id")
    if not department_id:
        raise ValidationFailed("请选择部门", code="department_required")
    unit = _latest_dept_unit(db, int(department_id))
    if unit is None:
        raise NotFound("该部门没有部门费用填报单位")
    unit = T.get_unit(db, unit.id, lock=True)
    T.ensure_writable(db, ctx, unit)
    name = (body.get("name") or "").strip()
    if not name:
        raise ValidationFailed("请填写专项名称", code="name_required")
    account_id = body.get("account_id")
    if not account_id:
        raise ValidationFailed("请选择所属预算科目", code="account_required")
    account = db.get(BudgetAccount, int(account_id))
    if account is None or not account.is_dept_expense or not account.is_active:
        raise ValidationFailed("请选择所属预算科目", code="account_required")
    version = db.get(BudgetVersion, unit.version_id)
    try:
        plan_month = parse_month(str(body.get("plan_month") or ""))
    except ValueError:
        raise ValidationFailed("请选择计划月份", code="plan_month_required") from None
    if plan_month.year != version.year:
        raise ValidationFailed("请选择计划月份", code="plan_month_required")
    amount = _money(body.get("amount"), required="请填写预留金额")
    r = Reserve(version_id=unit.version_id, department_id=unit.scope_object_id, account_id=account.id, name=name,
                amount=amount, plan_month=plan_month, created_by=actor.user.id, created_at=clock.now())
    db.add(r)
    T.mark_filling(unit)
    db.flush()
    write_audit(db, action="reserve.create", object_type="reserve", object_id=r.id, actor=actor, request=request,
                after={"name": name, "account": account.name, "plan_month": fmt_month(plan_month), "amount": amount})
    imported = imported_months(db)
    return {**reserve_view(db, r, dept_actuals(db, unit.scope_object_id), imported, version.year),
            "message": f"已新增「{name}」，{fmt_cny(amount)} 已计入{account.name} {fmt_month(plan_month)} 预算"}


def add_usage(db: Session, ctx: ScopeContext, actor: CurrentUser, reserve_id: int, body: dict, request=None) -> dict:
    """AC-F05-05：财务BP 登记专项实际使用（金额、日期、金蝶凭证号）。超出预留允许登记（DEC-F05-04）。"""
    if not ctx.has_role(Role.FINANCE_BP):
        raise Forbidden()
    r = db.get(Reserve, reserve_id)
    if r is None:
        raise NotFound("专项不存在")
    year = db.scalar(select(BudgetVersion.year).where(BudgetVersion.id == r.version_id))
    amount = _money(body.get("amount"), required="请填写使用金额")
    raw_date = (body.get("used_on") or "").strip() if isinstance(body.get("used_on"), str) else body.get("used_on")
    if not raw_date:
        raise ValidationFailed("请选择使用日期", code="used_on_required")
    try:
        used_on = date.fromisoformat(str(raw_date))
    except ValueError:
        raise ValidationFailed("请选择使用日期", code="used_on_required") from None
    if used_on.year != year:
        raise ValidationFailed(f"使用日期须在 {year} 年内", code="used_on_out_of_year")
    voucher = (body.get("voucher_no") or "").strip()
    if not voucher:
        raise ValidationFailed("请填写金蝶凭证号", code="voucher_required")
    u = ReserveUsage(reserve_id=r.id, amount=amount, used_on=used_on, voucher_no=voucher, created_by=actor.user.id,
                     created_at=clock.now())
    db.add(u)
    db.flush()
    write_audit(db, action="reserve.usage", object_type="reserve", object_id=r.id, actor=actor, request=request,
                after={"amount": amount, "used_on": used_on, "voucher_no": voucher})
    view = reserve_view(db, r, dept_actuals(db, r.department_id), imported_months(db), year)
    return {**view, "message": f"已登记，{r.name} 剩余 {fmt_cny(Decimal(view['remaining']))}"}

