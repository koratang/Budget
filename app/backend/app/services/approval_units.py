"""审批：填报单位（type = unit）与编制任务（type = task）——CMP-F07-01（AC-F07-01~06；SEQ-F07-01）。

跨组接口（第二期分工）：pending_items / detail / approve / reject；本模块同时服务两种类型，
detail / approve / reject 的 obj_type 关键字参数指明类型（缺省 unit）。user 为 CurrentUser（.user / .roles）。
服务函数只 flush，由路由 commit。
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.audit import write_audit
from app.core.clock import clock
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.money import fmt_amount, fmt_cny, fmt_foreign, fmt_percent
from app.core.scope import ScopeContext, load_scope
from app.models import (ApprovalRecord, AuditLog, B2bUnit, BCustomer, BudgetAccount, BudgetTask, BudgetVersion,
                        Category, DeptExpense, FillingUnit, FxBudget, PlatformUnit, Reserve, Site, Store, User,
                        UserRole)
from app.models.enums import Role, TaskStatus, UnitStatus, UnitType, VersionType
from app.services import filling as F
from app.services import tasking as T

TYPE_UNIT = "unit"
TYPE_TASK = "task"
ZERO = Decimal(0)


def _ctx(db: Session, user) -> ScopeContext:
    return load_scope(db, user.user.id, user.roles)


def _settings():
    return get_settings()


def _unit(db: Session, obj_id: int, *, lock: bool = False) -> FillingUnit:
    unit = T.get_unit(db, obj_id, lock=lock)
    if unit.task_id is None:
        raise NotFound("该审批事项已不存在或已被处理")
    return unit


def _task(db: Session, obj_id: int, *, lock: bool = False) -> BudgetTask:
    q = select(BudgetTask).where(BudgetTask.id == obj_id)
    task = db.scalar(q.with_for_update() if lock else q)
    if task is None:
        raise NotFound("该审批事项已不存在或已被处理")
    return task


def _record(db: Session, user, obj_type: str, obj_id: int, level: str, action: str, reason: str | None = None):
    db.add(ApprovalRecord(object_type=obj_type, object_id=obj_id, level=level, action=action, reason=reason,
                          approver_id=user.user.id, created_at=clock.now()))


def _ceo_names(db: Session) -> str:
    names = db.scalars(select(User.name).join(UserRole, UserRole.user_id == User.id)
                       .where(UserRole.role_code == Role.CEO, User.is_active).order_by(User.id)).all()
    return "、".join(names) or "CEO"


# ---------------------------------------------------------------------------
# 待我审批（AC-F07-01）
# ---------------------------------------------------------------------------
def unit_title(db: Session, unit: FillingUnit) -> str:
    task = T.task_of(db, unit)
    return f"{task.year} 年度预算 · {unit.name}" if task else unit.name


def task_title(task: BudgetTask) -> str:
    return f"{task.name} · 全公司预算"


def pending_items(db: Session, user) -> list[dict]:
    items: list[dict] = []
    units = db.scalars(select(FillingUnit).where(FillingUnit.task_id.is_not(None),
                                                 FillingUnit.status == UnitStatus.SUBMITTED,
                                                 FillingUnit.reviewer_id == user.user.id)
                       .order_by(FillingUnit.submitted_at, FillingUnit.id))
    for u in units:
        filler = db.get(User, u.filler_id)
        items.append({"type": TYPE_UNIT, "id": u.id, "title": unit_title(db, u), "kind_label": "预算编制",
                      "prev_step": f"{filler.name} 已提交", "step": "部门负责人审核",
                      "submitter": filler.name, "submitted_at": T.iso(u.submitted_at),
                      "link": f"/approvals/{TYPE_UNIT}/{u.id}"})
    if Role.CEO in user.roles:
        for task in db.scalars(select(BudgetTask).where(BudgetTask.status == TaskStatus.PENDING_CEO)
                               .order_by(BudgetTask.id)):
            done, total = T.submit_stats(db, task.id)
            at = db.scalar(select(func.max(ApprovalRecord.created_at)).where(
                ApprovalRecord.object_type == TYPE_UNIT, ApprovalRecord.action == "approve",
                ApprovalRecord.object_id.in_(select(FillingUnit.id).where(FillingUnit.task_id == task.id))))
            audit_at = task.created_at if at is None else at
            items.append({"type": TYPE_TASK, "id": task.id, "title": task_title(task), "kind_label": "预算编制",
                          "prev_step": f"全部 {total} 个填报单位已通过部门审核", "step": "CEO 审批",
                          "submitter": T.user_name(db, task.created_by), "submitted_at": T.iso(audit_at),
                          "link": f"/approvals/{TYPE_TASK}/{task.id}"})
    return items


# ---------------------------------------------------------------------------
# 详情（只读）
# ---------------------------------------------------------------------------
def _num(label: str, key: str) -> dict:
    return {"key": key, "label": label, "num": True}


def _txt(label: str, key: str) -> dict:
    return {"key": key, "label": label, "num": False}


def _platform_content(db: Session, unit: FillingUnit) -> dict:
    store = db.get(Store, unit.scope_object_id)
    site = db.get(Site, store.site_id)
    cats = dict(db.execute(select(Category.id, Category.name)).all())
    cat_sort = dict(db.execute(select(Category.id, Category.sort)).all())
    agg = db.execute(select(PlatformUnit.category_id, PlatformUnit.is_new, func.sum(PlatformUnit.sales_qty),
                            func.sum(PlatformUnit.revenue_local), func.sum(PlatformUnit.revenue_cny),
                            func.sum(PlatformUnit.gross_profit))
                     .where(PlatformUnit.version_id == unit.version_id, PlatformUnit.store_id == store.id)
                     .group_by(PlatformUnit.category_id, PlatformUnit.is_new)).all()
    agg.sort(key=lambda r: (cat_sort.get(r[0], 0), not r[1]))
    rows = []
    tot = defaultdict(lambda: ZERO)
    for cid, is_new, qty, rl, rc, gp in agg:
        for k, v in (("qty", qty), ("rl", rl), ("rc", rc), ("gp", gp)):
            tot[k] += v or ZERO
        rows.append({"store": store.name, "site": site.name, "category": f"{cats[cid]} · {'新品' if is_new else '老品'}",
                     "qty": F.fmt_calc("sales_qty", qty), "revenue_local": fmt_foreign(rl or ZERO, store.currency),
                     "revenue_cny": fmt_amount(rc), "gross_profit": fmt_amount(gp),
                     "gross_margin": fmt_percent(F.margin_of(gp, rc), 1)})
    rate = db.scalar(select(FxBudget.rate).join(BudgetVersion, BudgetVersion.year == FxBudget.year)
                     .where(BudgetVersion.id == unit.version_id, FxBudget.currency == store.currency))
    return {"kind": "table",
            "note": f"预算汇率 {store.currency} {rate if rate is not None else '未录入'}（示例值，以财务BP录入为准）",
            "columns": [_txt("店铺", "store"), _txt("站点", "site"), _txt("品类", "category"),
                        _num("全年销量（件）", "qty"), _num(f"本币收入（{store.currency}）", "revenue_local"),
                        _num("人民币收入", "revenue_cny"), _num("毛利", "gross_profit"), _num("毛利率", "gross_margin")],
            "rows": rows,
            "total": {"store": "合计", "qty": F.fmt_calc("sales_qty", tot["qty"]),
                      "revenue_local": fmt_foreign(tot["rl"], store.currency), "revenue_cny": fmt_amount(tot["rc"]),
                      "gross_profit": fmt_amount(tot["gp"]),
                      "gross_margin": fmt_percent(F.margin_of(tot["gp"], tot["rc"]), 1)}}


def _b2b_content(db: Session, unit: FillingUnit) -> dict:
    agg = db.execute(select(BCustomer.name, BCustomer.currency, func.sum(B2bUnit.sales_local),
                            func.sum(B2bUnit.revenue_cny), func.sum(B2bUnit.gross_profit))
                     .join(BCustomer, BCustomer.id == B2bUnit.customer_id)
                     .where(B2bUnit.version_id == unit.version_id, BCustomer.department_id == unit.scope_object_id)
                     .group_by(BCustomer.name, BCustomer.currency, BCustomer.id).order_by(BCustomer.id)).all()
    rows, rc_t, gp_t = [], ZERO, ZERO
    for name, cur, sl, rc, gp in agg:
        rc_t += rc or ZERO
        gp_t += gp or ZERO
        rows.append({"customer": name, "sales_local": fmt_foreign(sl or ZERO, cur), "revenue_cny": fmt_amount(rc),
                     "gross_profit": fmt_amount(gp), "gross_margin": fmt_percent(F.margin_of(gp, rc), 1)})
    return {"kind": "table", "note": None,
            "columns": [_txt("B 端客户", "customer"), _num("全年销售额（本币）", "sales_local"),
                        _num("人民币收入", "revenue_cny"), _num("毛利", "gross_profit"), _num("毛利率", "gross_margin")],
            "rows": rows,
            "total": {"customer": "合计", "revenue_cny": fmt_amount(rc_t), "gross_profit": fmt_amount(gp_t),
                      "gross_margin": fmt_percent(F.margin_of(gp_t, rc_t), 1)}}


def _dept_content(db: Session, unit: FillingUnit) -> dict:
    daily = dict(db.execute(select(DeptExpense.account_id, func.sum(DeptExpense.amount))
                            .where(DeptExpense.version_id == unit.version_id,
                                   DeptExpense.department_id == unit.scope_object_id)
                            .group_by(DeptExpense.account_id)).all())
    res = dict(db.execute(select(Reserve.account_id, func.sum(Reserve.amount))
                          .where(Reserve.version_id == unit.version_id, Reserve.department_id == unit.scope_object_id)
                          .group_by(Reserve.account_id)).all())
    accounts = db.scalars(select(BudgetAccount).where(BudgetAccount.id.in_(set(daily) | set(res)))
                          .order_by(BudgetAccount.sort, BudgetAccount.id))
    rows, tot = [], ZERO
    for a in accounts:
        d, r = daily.get(a.id) or ZERO, res.get(a.id) or ZERO
        tot += d + r
        rows.append({"account": a.name, "daily": fmt_amount(d), "reserve": fmt_amount(r) if r else "—",
                     "total": fmt_amount(d + r)})
    return {"kind": "table", "note": None,
            "columns": [_txt("预算科目", "account"), _num("全年日常预算", "daily"), _num("专项预留", "reserve"),
                        _num("全年预算合计", "total")],
            "rows": rows, "total": {"account": "部门合计", "total": fmt_amount(tot)}}


def _ratio_content(db: Session, unit: FillingUnit) -> dict:
    """比例单位：按标签列出各维度组合全年取值（各月不同时为区间）。"""
    ctx = ScopeContext(user_id=0, roles=frozenset({Role.FINANCE_HEAD}))
    tabs = F.TABS[unit.unit_type]
    rows = []
    for tab in tabs:
        grid = F.ratio_grid(db, ctx, unit, tab)
        dims = [c["key"] for c in grid["columns"] if c["kind"] == "dim"]
        months = [c["key"] for c in grid["columns"] if c["kind"] == "value" and c["key"] != "year_total"]
        for r in grid["rows"]:
            if r.get("kind") != "input":
                continue
            vals = [r["values"].get(m) for m in months if r["values"].get(m) is not None]
            label = " · ".join(str(r["values"].get(d)) for d in dims if r["values"].get(d))
            uniq = sorted(set(vals), key=vals.index)
            rows.append({"dims": label, "value": uniq[0] if len(uniq) == 1 else f"{vals[0]} 等（各月不同）"})
    return {"kind": "table", "note": None,
            "columns": [_txt("维度 · 项目", "dims"), _num("1–12 月取值", "value")], "rows": rows, "total": None}


def unit_content(db: Session, unit: FillingUnit) -> dict:
    if unit.unit_type == UnitType.PLATFORM:
        return _platform_content(db, unit)
    if unit.unit_type == UnitType.B2B:
        return _b2b_content(db, unit)
    if unit.unit_type == UnitType.DEPT_EXPENSE:
        return _dept_content(db, unit)
    return _ratio_content(db, unit)


def task_content(db: Session, task: BudgetTask) -> dict:
    pl = F.version_pl(db, task.version_id)
    quarters = []
    for q in range(4):
        ms = pl["months"][q * 3:(q + 1) * 3]
        vals = {k: sum((Decimal(m[k]) for m in ms), ZERO)
                for k in ("revenue_cny", "gross_profit", "dept_expense", "other_pl", "net_profit")}
        quarters.append({"label": f"Q{q + 1}", **{k: fmt_amount(v) for k, v in vals.items()},
                         "net_margin": fmt_percent(F.margin_of(vals["net_profit"], vals["revenue_cny"]), 1)})
    t = pl["total"]
    quarters.append({"label": "全年", **{k: t[f"{k}_display"] for k in ("revenue_cny", "gross_profit", "dept_expense",
                                                                       "other_pl", "net_profit")},
                     "net_margin": t["net_margin_display"]})
    done, total = T.submit_stats(db, task.id)
    return {"kind": "company",
            "note": f"全部 {total} 个填报单位已通过部门审核",
            "kpis": {"revenue": fmt_cny(Decimal(t["revenue_cny"])), "gross_profit": fmt_cny(Decimal(t["gross_profit"])),
                     "gross_margin": t["gross_margin_display"], "dept_expense": fmt_cny(Decimal(t["dept_expense"])),
                     "net_profit": fmt_cny(Decimal(t["net_profit"])), "net_margin": t["net_margin_display"]},
            "quarters": quarters,
            "segments": [{"name": c["name"], "kind_label": "平台渠道", "revenue": c["revenue_display"],
                          "gross_profit": c["gross_profit_display"], "gross_margin": c["gross_margin_display"]}
                         for c in pl["channels"]]
                        + [{"name": c["name"], "kind_label": "B端", "revenue": c["revenue_display"],
                            "gross_profit": c["gross_profit_display"], "gross_margin": c["gross_margin_display"]}
                           for c in pl["customers"]],
            "total": {"revenue": t["revenue_cny_display"], "gross_profit": t["gross_profit_display"],
                      "gross_margin": t["gross_margin_display"]}}


def _records(db: Session, obj_type: str, obj_id: int) -> list[ApprovalRecord]:
    return list(db.scalars(select(ApprovalRecord).where(ApprovalRecord.object_type == obj_type,
                                                        ApprovalRecord.object_id == obj_id)
                           .order_by(ApprovalRecord.id)))


def _has_handled(db: Session, user, obj_type: str, obj_id: int) -> bool:
    return any(r.approver_id == user.user.id for r in _records(db, obj_type, obj_id))


def _unit_detail(db: Session, user, unit: FillingUnit) -> dict:
    ctx = _ctx(db, user)
    if not (T.can_view(db, ctx, unit) or _has_handled(db, user, TYPE_UNIT, unit.id)):
        raise Forbidden()
    task = T.task_of(db, unit)
    filler, reviewer = db.get(User, unit.filler_id), db.get(User, unit.reviewer_id)
    recs = _records(db, TYPE_UNIT, unit.id)
    last_dept = next((r for r in reversed(recs) if r.level == "dept_head"), None)
    dept_result = ("待审核" if unit.status == UnitStatus.SUBMITTED else
                   ("已通过" if last_dept and last_dept.action == "approve" else
                    ("已退回" if last_dept else "未开始")))
    chain = [
        {"label": "填报人提交", "who": f"{filler.name}（{UnitType.LABELS[unit.unit_type]}）",
         "result": "已提交" if unit.submitted_at else "未提交", "at": T.fmt_dt(unit.submitted_at), "state": "done"},
        {"label": "部门负责人审核", "who": reviewer.name, "result": dept_result,
         "at": T.fmt_dt(last_dept.created_at) if last_dept and unit.status != UnitStatus.SUBMITTED else None,
         "state": "current" if unit.status == UnitStatus.SUBMITTED else ("done" if last_dept else "todo")},
        {"label": "CEO 审批（全公司预算）", "who": _ceo_names(db),
         "result": "已锁定为年初原始目标" if task and task.status == TaskStatus.COMPLETED else "待进行",
         "at": T.fmt_dt(task.completed_at) if task and task.completed_at else None,
         "state": "done" if task and task.status == TaskStatus.COMPLETED else "todo"},
    ]
    can_act = unit.status == UnitStatus.SUBMITTED and unit.reviewer_id == user.user.id
    return {"type": TYPE_UNIT, "id": unit.id, "title": unit_title(db, unit), "kind_label": "预算编制",
            "status": unit.status, "status_label": UnitStatus.LABELS[unit.status],
            "submitter": filler.name, "submitted_at": T.fmt_dt(unit.submitted_at), "chain": chain,
            "can_act": can_act, "approve_label": "通过",
            "approve_hint": f"通过后该单位状态变为「已通过」，计入「{task.name if task else ''}」进度。",
            "reject_hint": "退回后该单位状态变为「已退回」并解除锁定，填报页显示退回原因，同时钉钉通知填报人。",
            "unit": T.unit_info(db, None, unit), "content": unit_content(db, unit),
            "history": [{"level": r.level, "action": r.action, "reason": r.reason,
                         "who": T.user_name(db, r.approver_id), "at": T.fmt_dt(r.created_at)} for r in recs]}


def _ceo_submitted_at(db: Session, task: BudgetTask):
    """最近一次「提交 CEO 审批」的时间（审计日志 task.submit_to_ceo）。"""
    return db.scalar(select(func.max(AuditLog.occurred_at)).where(
        AuditLog.action == "task.submit_to_ceo", AuditLog.object_type == "budget_task",
        AuditLog.object_id == str(task.id)))


def _task_detail(db: Session, user, task: BudgetTask) -> dict:
    if not (Role.CEO in user.roles or Role.FINANCE_HEAD in user.roles):
        raise Forbidden()
    done, total = T.submit_stats(db, task.id)
    recs = _records(db, TYPE_TASK, task.id)
    last = recs[-1] if recs else None
    version = db.get(BudgetVersion, task.version_id)
    chain = [
        {"label": "部门负责人审核", "who": f"全部 {total} 个填报单位",
         "result": "已全部通过" if task.status != TaskStatus.IN_PROGRESS or done == total else "进行中",
         "at": None, "state": "done"},
        {"label": "财务负责人提交", "who": T.user_name(db, task.created_by),
         "result": "已提交" if task.status != TaskStatus.IN_PROGRESS else "待提交", "at": None,
         "state": "done" if task.status != TaskStatus.IN_PROGRESS else "current"},
        {"label": "CEO 审批", "who": _ceo_names(db),
         "result": {TaskStatus.PENDING_CEO: "待审批", TaskStatus.COMPLETED: "已通过并锁定"}.get(
             task.status, "已退回" if task.ceo_return_reason else "待进行"),
         "at": T.fmt_dt(last.created_at) if last and task.status != TaskStatus.PENDING_CEO else None,
         "state": "current" if task.status == TaskStatus.PENDING_CEO else
         ("done" if task.status == TaskStatus.COMPLETED else "todo")},
    ]
    status_label = ("已锁定为年初原始目标" if task.status == TaskStatus.COMPLETED else T.task_status_label(task))
    return {"type": TYPE_TASK, "id": task.id, "title": task_title(task), "kind_label": "预算编制",
            "status": task.status, "status_label": status_label,
            "submitter": T.user_name(db, task.created_by), "submitted_at": T.fmt_dt(_ceo_submitted_at(db, task)),
            "chain": chain,
            "can_act": task.status == TaskStatus.PENDING_CEO and Role.CEO in user.roles,
            "approve_label": "通过并锁定",
            "approve_hint": f"通过后保存为「年初原始目标」，此后任何角色都不能直接修改其数值；{task.year} 年度预算汇率随之冻结。",
            "reject_hint": "退回后编制任务回到财务负责人并显示原因，财务负责人可把指定单位退回其填报人。",
            "version": {"id": version.id, "name": version.name, "type": version.type, "locked": version.locked},
            "task": T.task_row(db, task), "content": task_content(db, task),
            "history": [{"level": r.level, "action": r.action, "reason": r.reason,
                         "who": T.user_name(db, r.approver_id), "at": T.fmt_dt(r.created_at)} for r in recs]}


def detail(db: Session, user, obj_id: int, obj_type: str = TYPE_UNIT) -> dict:
    if obj_type == TYPE_TASK:
        return _task_detail(db, user, _task(db, obj_id))
    return _unit_detail(db, user, _unit(db, obj_id))


# ---------------------------------------------------------------------------
# 通过 / 退回（AC-F07-02~06）
# ---------------------------------------------------------------------------
def _transition_unit(db: Session, unit: FillingUnit, expect: str, **values) -> None:
    res = db.execute(update(FillingUnit).where(FillingUnit.id == unit.id, FillingUnit.status == expect)
                     .values(updated_at=clock.now(), **values).execution_options(synchronize_session=False))
    if res.rowcount != 1:
        raise Conflict("状态已变化，请刷新", code="status_changed")
    db.refresh(unit)


def _approve_unit(db: Session, user, unit: FillingUnit) -> dict:
    if unit.reviewer_id != user.user.id:
        raise Forbidden()
    _transition_unit(db, unit, UnitStatus.SUBMITTED, status=UnitStatus.APPROVED)
    _record(db, user, TYPE_UNIT, unit.id, "dept_head", "approve")
    write_audit(db, action="unit.approve", object_type="filling_unit", object_id=unit.id, actor=user,
                before={"status": UnitStatus.SUBMITTED}, after={"status": UnitStatus.APPROVED})
    db.flush()
    return {"type": TYPE_UNIT, "id": unit.id, "status": unit.status, "status_label": UnitStatus.LABELS[unit.status],
            "message": f"已通过「{unit.name}」"}


def _reject_unit(db: Session, user, unit: FillingUnit, reason: str | None) -> dict:
    if unit.reviewer_id != user.user.id:
        raise Forbidden()
    text = T.require_reason(reason)
    _transition_unit(db, unit, UnitStatus.SUBMITTED, status=UnitStatus.RETURNED, return_reason=text)
    _record(db, user, TYPE_UNIT, unit.id, "dept_head", "reject", text)
    write_audit(db, action="unit.reject", object_type="filling_unit", object_id=unit.id, actor=user,
                before={"status": UnitStatus.SUBMITTED}, after={"status": UnitStatus.RETURNED, "reason": text})
    task = T.task_of(db, unit)
    T.notify(db, biz_type="unit_returned", biz_id=unit.id, user_ids=[unit.filler_id],
             title="【预算管理平台】你的填报被退回", name=task.name, object_name=unit.name,
             period=f"{task.year} 年度", link=T.app_link(_settings(), T.fill_path(unit)))
    db.flush()
    return {"type": TYPE_UNIT, "id": unit.id, "status": unit.status, "status_label": UnitStatus.LABELS[unit.status],
            "message": f"已退回「{unit.name}」，已通知填报人"}


def _approve_task(db: Session, user, task: BudgetTask) -> dict:
    """CEO 通过：同一事务内 任务 → 已完成；编制稿 → 年初原始目标（锁定）；该年度预算汇率随之冻结（DEC-020）。"""
    if Role.CEO not in user.roles:
        raise Forbidden()
    if task.status != TaskStatus.PENDING_CEO:
        raise Conflict("状态已变化，请刷新", code="status_changed")
    now = clock.now()
    version = db.get(BudgetVersion, task.version_id)
    no = (db.scalar(select(func.max(BudgetVersion.version_no)).where(
        BudgetVersion.year == task.year, BudgetVersion.type == VersionType.ORIGINAL_TARGET)) or 0) + 1
    before = {"type": version.type, "locked": version.locked, "name": version.name}
    db.execute(update(BudgetVersion).where(BudgetVersion.id == version.id, BudgetVersion.locked.is_(False))
               .values(type=VersionType.ORIGINAL_TARGET, version_no=no, locked=True,
                       name=f"{task.year} 年初原始目标", approved_by=user.user.id, approved_at=now)
               .execution_options(synchronize_session=False))
    task.status = TaskStatus.COMPLETED
    task.completed_at = now
    _record(db, user, TYPE_TASK, task.id, "ceo", "approve")
    db.flush()
    db.refresh(version)
    write_audit(db, action="version.lock_original_target", object_type="budget_version", object_id=version.id,
                actor=user, before=before,
                after={"type": version.type, "version_no": version.version_no, "locked": True,
                       "approved_by": user.user.name, "approved_at": now})
    finance_heads = list(db.scalars(select(UserRole.user_id).where(UserRole.role_code == Role.FINANCE_HEAD)))
    T.notify(db, biz_type="task_approved", biz_id=task.id, user_ids=finance_heads,
             title="【预算管理平台】全公司预算已通过并锁定", name=task.name, object_name="年初原始目标",
             period=f"{task.year} 年度", link=T.app_link(_settings(), f"/tasks/{task.id}"))
    db.flush()
    return {"type": TYPE_TASK, "id": task.id, "status": task.status, "status_label": "已锁定为年初原始目标",
            "version": {"id": version.id, "name": version.name, "type": version.type,
                        "version_no": version.version_no, "locked": version.locked},
            "message": f"已通过并锁定为「{version.name}」"}


def _reject_task(db: Session, user, task: BudgetTask, reason: str | None) -> dict:
    if Role.CEO not in user.roles:
        raise Forbidden()
    text = T.require_reason(reason)
    if task.status != TaskStatus.PENDING_CEO:
        raise Conflict("状态已变化，请刷新", code="status_changed")
    task.status = TaskStatus.IN_PROGRESS
    task.ceo_return_reason = text
    _record(db, user, TYPE_TASK, task.id, "ceo", "reject", text)
    write_audit(db, action="task.ceo_reject", object_type="budget_task", object_id=task.id, actor=user,
                before={"status": TaskStatus.PENDING_CEO}, after={"status": TaskStatus.IN_PROGRESS, "reason": text})
    finance_heads = list(db.scalars(select(UserRole.user_id).where(UserRole.role_code == Role.FINANCE_HEAD)))
    T.notify(db, biz_type="task_returned", biz_id=task.id, user_ids=finance_heads,
             title="【预算管理平台】全公司预算被 CEO 退回", name=task.name, object_name="请查看退回原因",
             period=f"{task.year} 年度", link=T.app_link(_settings(), f"/tasks/{task.id}"))
    db.flush()
    return {"type": TYPE_TASK, "id": task.id, "status": task.status, "status_label": "CEO 已退回",
            "message": "已退回财务负责人"}


def approve(db: Session, user, obj_id: int, obj_type: str = TYPE_UNIT) -> dict:
    if obj_type == TYPE_TASK:
        return _approve_task(db, user, _task(db, obj_id, lock=True))
    return _approve_unit(db, user, _unit(db, obj_id, lock=True))


def reject(db: Session, user, obj_id: int, reason: str, obj_type: str = TYPE_UNIT) -> dict:
    if obj_type == TYPE_TASK:
        return _reject_task(db, user, _task(db, obj_id, lock=True), reason)
    return _reject_unit(db, user, _unit(db, obj_id, lock=True), reason)

