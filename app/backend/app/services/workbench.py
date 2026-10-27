"""工作台（API-F00-01，PAGE-F00-01，DEC-001）：按角色聚合我的待办与关键数。

- 待填报：当前用户负责、状态为未开始 / 填报中 / 调整中 / 已退回的填报单位（AC-F03-03）。
- 待审批：按第二期分工的跨组签名 pending_items(db, user) 从各审批服务模块汇总；模块尚未提供时该类型为空。
- 未处理预警：数据范围内、状态为未处理的预警（REQ-F11-01）。
- 关键数（CEO、财务负责人）：净利润达成率双口径与公司汇总共用 reports.achievement（AC-F10-08）、
  最近季度预测偏差（AC-F10-10）、编制任务提交率（（已提交 + 已通过）÷ 全部，DEC-026）。
- 导入与核对（财务BP）：金蝶、BI 最近导入期间与 BI 与金蝶差异超 3% 的「店铺 × 站点」组合数（AC-F09-07）。
"""
from __future__ import annotations

import importlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.calc import formulas as F
from app.calc.periods import fmt_month
from app.core.auth import CurrentUser
from app.core.clock import TZ, clock
from app.core.scope import ScopeContext
from app.models import (Alert, BiActualAgg, BudgetAccount, BudgetTask, FillingUnit, ImportBatch, KingdeeActual, Rule,
                        RuleVersion, Store, TargetAdjustment)
from app.models.enums import AlertStatus, ImportStatus, Role, TaskStatus, UnitStatus, UnitType
from app.services import reports as R

ITEM_LIMIT = 5
TODO_STATUSES = (UnitStatus.NOT_STARTED, UnitStatus.FILLING, UnitStatus.ADJUSTING, UnitStatus.RETURNED)
SUBMITTED_STATUSES = (UnitStatus.SUBMITTED, UnitStatus.APPROVED)

# 跨组审批服务模块（第二期分工「跨组接口」）
APPROVAL_MODULES = ("app.services.approval_units", "app.services.adjustments", "app.services.rules")

FILL_LINKS = {
    UnitType.PLATFORM: "/filling/platform/{id}",
    UnitType.B2B: "/filling/b2b/{id}",
    UnitType.COST_RATIO: "/filling/cost/{id}",
    UnitType.LOGISTICS_RATIO: "/filling/logistics/{id}",
    UnitType.DEPT_EXPENSE: "/dept-expense?unitId={id}",
}


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(TZ).isoformat()
    return str(v)


# ---------------------------------------------------------------------------
# 我的待办
# ---------------------------------------------------------------------------
def filling_todo(db: Session, user_id: int) -> dict:
    q = (select(FillingUnit, BudgetTask, TargetAdjustment)
         .outerjoin(BudgetTask, BudgetTask.id == FillingUnit.task_id)
         .outerjoin(TargetAdjustment, TargetAdjustment.id == FillingUnit.adjustment_id)
         .where(FillingUnit.filler_id == user_id, FillingUnit.status.in_(TODO_STATUSES))
         .order_by(FillingUnit.updated_at.desc(), FillingUnit.id.desc()))
    rows = db.execute(q).all()
    items = []
    for unit, task, adj in rows[:ITEM_LIMIT]:
        name = task.name if task else (f"{adj.year} 年第 {adj.quarter} 季度目标调整" if adj else "")
        items.append({"id": unit.id, "task_name": name, "unit_name": unit.name, "unit_type": unit.unit_type,
                      "status": unit.status, "status_label": UnitStatus.LABELS[unit.status],
                      "deadline": task.deadline.isoformat() if task else None,
                      "return_reason": unit.return_reason,
                      "link": FILL_LINKS[unit.unit_type].format(id=unit.id)})
    return {"count": len(rows), "items": items}


def _pending_from(module_name: str, db: Session, user: CurrentUser) -> list[dict]:
    """安全导入跨组审批模块：模块或 pending_items 尚未提供时返回空列表；已提供则按签名调用（错误照常抛出）。"""
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name == module_name:
            return []
        raise
    fn = getattr(module, "pending_items", None)
    return list(fn(db, user)) if fn is not None else []


def approval_todo(db: Session, user: CurrentUser) -> dict:
    items: list[dict] = []
    for name in APPROVAL_MODULES:
        items.extend(_pending_from(name, db, user))
    items.sort(key=lambda x: _iso(x.get("submitted_at")) or "", reverse=True)
    return {"count": len(items), "items": [{**it, "submitted_at": _iso(it.get("submitted_at"))}
                                           for it in items[:ITEM_LIMIT]]}


def _alert_scope(ctx: ScopeContext):
    """预警对象按类型落到数据范围：店铺 / 渠道 / 部门 / B 端客户；其他（品类、公司）只对全公司范围角色可见。"""
    if ctx.all_company:
        return None
    parts = []
    for obj_type, ids in (("store", ctx.store_ids), ("channel", ctx.channel_ids), ("department", ctx.department_ids),
                          ("customer", ctx.customer_ids)):
        if ids:
            parts.append((Alert.object_type == obj_type) & Alert.object_id.in_([str(i) for i in ids]))
    return or_(*parts) if parts else Alert.id.is_(None)


def alert_todo(db: Session, ctx: ScopeContext) -> dict:
    q = (select(Alert, RuleVersion.version_no, Rule.name).join(RuleVersion, RuleVersion.id == Alert.rule_version_id)
         .join(Rule, Rule.id == RuleVersion.rule_id).where(Alert.status == AlertStatus.OPEN))
    clause = _alert_scope(ctx)
    if clause is not None:
        q = q.where(clause)
    rows = db.execute(q.order_by(Alert.created_at.desc(), Alert.id.desc())).all()
    items = [{"id": a.id, "object_name": a.object_name, "period": fmt_month(a.period), "rule_name": name,
              "rule_version": f"v{vno}", "link": f"/alerts?id={a.id}"} for a, vno, name in rows[:ITEM_LIMIT]]
    return {"count": len(rows), "items": items}


# ---------------------------------------------------------------------------
# 关键数（CEO、财务负责人）
# ---------------------------------------------------------------------------
def latest_forecast(db: Session, year: int) -> dict | None:
    """最近一个已发布快照季度中、已导入金蝶实际各月的偏差；该季度尚无实际时回看上一个快照季度。"""
    acc = R.forecast_accuracy(db, year)
    if not acc:
        return None
    quarters = sorted({a["quarter"] for a in acc}, reverse=True)
    for q in quarters:
        months = [a for a in acc if a["quarter"] == q and a["actual_imported"]]
        if months:
            return {"quarter": q, "snapshot": months[0]["snapshot"], "months": months}
    q = quarters[0]
    snap = next(a for a in acc if a["quarter"] == q)
    return {"quarter": q, "snapshot": snap["snapshot"], "months": []}


def submit_rate(db: Session) -> dict:
    task = db.scalar(select(BudgetTask).where(BudgetTask.status == TaskStatus.IN_PROGRESS)
                     .order_by(BudgetTask.created_at.desc()).limit(1))
    in_progress = task is not None
    if task is None:
        task = db.scalar(select(BudgetTask).order_by(BudgetTask.created_at.desc(), BudgetTask.id.desc()).limit(1))
    if task is None:
        return {"task": None, "in_progress": False}
    statuses = db.scalars(select(FillingUnit.status).where(FillingUnit.task_id == task.id)).all()
    total = len(statuses)
    done = sum(1 for st in statuses if st in SUBMITTED_STATUSES)
    rate = Decimal(done) / Decimal(total) if total else None
    return {"task": {"id": task.id, "name": task.name, "status": task.status,
                     "status_label": TaskStatus.LABELS[task.status]},
            "in_progress": in_progress, "submitted": done, "total": total, "rate": R.pct(rate)}


# ---------------------------------------------------------------------------
# 导入与核对（财务BP）
# ---------------------------------------------------------------------------
def reconcile_flagged(db: Session) -> dict:
    """最近一个金蝶与 BI 都已导入的月份中，「店铺 × 站点」|差异率| > 3% 的组合数（缺当月平均汇率的组合不计算）。"""
    both = sorted(set(R.kingdee_months(db)) & set(R.bi_months(db)))
    if not both:
        return {"month": None, "count": 0}
    m = both[-1]
    eff = select(ImportBatch.id).where(ImportBatch.status == ImportStatus.EFFECTIVE)
    kd: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    q = (select(KingdeeActual.store_id, Store.site_id, KingdeeActual.amount)
         .join(BudgetAccount, BudgetAccount.id == KingdeeActual.account_id)
         .join(Store, Store.id == KingdeeActual.store_id)
         .where(KingdeeActual.batch_id.in_(eff), KingdeeActual.month == m, BudgetAccount.pl_item == "revenue"))
    for sid, site, amount in db.execute(q).all():
        kd[(sid, site)] += amount
    bi: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    cur: dict[tuple[int, int], str] = {}
    q = select(BiActualAgg).where(BiActualAgg.batch_id.in_(eff), BiActualAgg.month == m)
    for agg in db.scalars(q).all():
        bi[(agg.store_id, agg.site_id)] += agg.revenue_local
        cur[(agg.store_id, agg.site_id)] = agg.currency
    fx = R.actual_fx(db, m)
    count = 0
    for key, local in bi.items():
        if key not in kd:
            continue
        result = F.reconcile(local, fx.get(cur[key]), kd[key])
        if result.flagged:
            count += 1
    return {"month": fmt_month(m), "count": count}


def import_status(db: Session) -> dict:
    kd = R.kingdee_months(db)
    bi = R.bi_months(db)
    return {"kingdee_latest": fmt_month(kd[-1]) if kd else None,
            "bi_latest": fmt_month(bi[-1]) if bi else None,
            "bi_recent_months": [fmt_month(m) for m in bi[-2:]],
            "reconcile": reconcile_flagged(db)}


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def workbench(db: Session, user: CurrentUser, ctx: ScopeContext) -> dict:
    year = R.default_year(db)
    latest = R.latest_kingdee_month(db)
    today = clock.today()
    out = {
        "user": {"id": user.user.id, "name": user.user.name, "role_names": user.role_names},
        "today": today.isoformat(), "year": year, "kingdee_latest": fmt_month(latest) if latest else None,
        "todo": {"filling": filling_todo(db, user.user.id), "approvals": approval_todo(db, user),
                 "alerts": alert_todo(db, ctx)},
        "filling_list_link": "/dept-expense" if user.roles == {Role.DEPT_BUDGET} else "/filling",
        "key_metrics": None, "imports": None,
    }
    if ctx.has_role(Role.CEO, Role.FINANCE_HEAD):
        ach = R.achievement(db, year)
        if ach is not None:
            ach.pop("_actuals")
            ach.pop("months")
        out["key_metrics"] = {"achievement": ach, "forecast": latest_forecast(db, year), "submit": submit_rate(db)}
    if ctx.has_role(Role.FINANCE_BP):
        out["imports"] = import_status(db)
    return out
