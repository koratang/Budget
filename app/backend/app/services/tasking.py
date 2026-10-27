"""编制任务服务 CMP-F03-01（REQ-F03-01/02、AC-F03-01~05、AC-F07-04/06；SEQ-F03-01；DEC-026）。

- 发布任务：同年度未完成任务唯一 → 按 AC-F03-05 生成填报单位（缺填报人或审核人整次失败）→
  建编制稿版本与全部预算数据行（默认 0）→ 审计 → 发件箱（每位填报人一条，不含金额）。
- 进度：五种状态、提交率 =（已提交 + 已通过）÷ 全部单位（DEC-026）、逾期标记。
- 逾期提醒：截止日期次日 09:00 起，状态不是已提交 / 已通过的单位向填报人及其部门负责人各发一条（AC-F03-04）。
- 提交 CEO：仍有未通过单位时阻止并列出（AC-F07-04）；CEO 退回后财务负责人可把指定单位退回填报人（AC-F07-06）。
另提供 G2 各服务共用的单位访问判断、时间格式化与通知辅助函数。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.calc.periods import fmt_month, year_months
from app.core.audit import write_audit
from app.core.auth import CurrentUser
from app.core.clock import TZ, clock
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.scope import ScopeContext
from app.dingtalk.outbox import build_notice, enqueue_notice
from app.dingtalk.scheduler import register_overdue_hook
from app.models import (ApprovalRecord, AuditLog, B2bUnit, BCustomer, BudgetAccount, BudgetTask, BudgetVersion,
                        Category, ChannelCategoryRatio, ChannelSiteRatio, CompanyOtherPl, Department, DeptExpense,
                        FillingUnit, PlatformUnit, Store, TargetAdjustment, User, UserRole, UserScope)
from app.models.enums import AdjustmentStatus, OtherPlItem, Role, ScopeType, TaskStatus, UnitStatus, UnitType, VersionType

# 单位类型显示顺序（与原型一致）
UNIT_TYPE_ORDER = (UnitType.PLATFORM, UnitType.B2B, UnitType.COST_RATIO, UnitType.LOGISTICS_RATIO,
                   UnitType.DEPT_EXPENSE)
# 「我的填报」排序：已退回最前，其次未开始、填报中、已提交、已通过（PAGE-F04-01）
STATUS_SORT = {UnitStatus.RETURNED: 0, UnitStatus.NOT_STARTED: 1, UnitStatus.FILLING: 2, UnitStatus.ADJUSTING: 2,
               UnitStatus.SUBMITTED: 3, UnitStatus.DEPT_APPROVED: 3, UnitStatus.APPROVED: 4}
DONE_STATUSES = (UnitStatus.SUBMITTED, UnitStatus.APPROVED)
OVERDUE_AT = time(9, 0)
RETURN_REASON_REQUIRED = "请填写退回原因"
LOCKED_MESSAGE = "已提交，退回后才能修改"
VERSION_LOCKED_MESSAGE = "版本已锁定，不能修改"


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------
def fmt_dt(value: datetime | None) -> str | None:
    """'2026-12-18 10:05'（Asia/Shanghai）。"""
    if value is None:
        return None
    return value.astimezone(TZ).strftime("%Y-%m-%d %H:%M")


def iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def user_name(db: Session, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    return db.scalar(select(User.name).where(User.id == user_id))


def app_link(settings, path: str) -> str:
    return settings.APP_BASE_URL.rstrip("/") + path


def notify(db: Session, *, biz_type: str, biz_id: int | None, user_ids: list[int], title: str, name: str,
           object_name: str = "", period: str = "", link: str) -> None:
    """按用户 ID 写发件箱（钉钉 userid），内容经 build_notice 白名单校验（NFR-005）。"""
    userids = list(db.scalars(select(User.dingtalk_userid).where(User.id.in_(set(user_ids)), User.is_active)))
    enqueue_notice(db, biz_type=biz_type, biz_id=biz_id, receivers=userids,
                   content=build_notice(title=title, name=name, object_name=object_name, period=period, link=link))


def require_reason(reason: str | None, message: str = RETURN_REASON_REQUIRED) -> str:
    text = (reason or "").strip()
    if not text:
        raise ValidationFailed(message, code="reason_required")
    return text


def task_of(db: Session, unit: FillingUnit) -> BudgetTask | None:
    return db.get(BudgetTask, unit.task_id) if unit.task_id else None


def get_unit(db: Session, unit_id: int, *, lock: bool = False) -> FillingUnit:
    q = select(FillingUnit).where(FillingUnit.id == unit_id)
    if lock:
        q = q.with_for_update()
    unit = db.scalar(q)
    if unit is None:
        raise NotFound("填报单位不存在")
    return unit


def unit_department_id(db: Session, unit: FillingUnit) -> int | None:
    """单位所属部门：B 端 / 部门费用 = scope_object_id；其余为填报人所属部门。"""
    if unit.unit_type in (UnitType.B2B, UnitType.DEPT_EXPENSE):
        return unit.scope_object_id
    return db.scalar(select(User.department_id).where(User.id == unit.filler_id))


def b2b_customer_ids(db: Session, department_id: int) -> list[int]:
    return list(db.scalars(select(BCustomer.id).where(BCustomer.department_id == department_id)
                           .order_by(BCustomer.id)))


def can_fill(db: Session, ctx: ScopeContext, unit: FillingUnit) -> bool:
    """填报权限：角色 + 数据范围（同范围的其他填报人同样可写，如 FLOW-15 的刘畅）。"""
    t = unit.unit_type
    if t == UnitType.PLATFORM:
        if not ctx.has_role(Role.OPERATIONS):
            return False
        store = db.get(Store, unit.scope_object_id)
        return store is not None and (store.id in ctx.store_ids or store.channel_id in ctx.channel_ids)
    if t == UnitType.B2B:
        return ctx.has_role(Role.B2B) and bool(set(b2b_customer_ids(db, unit.scope_object_id)) & ctx.customer_ids)
    if t == UnitType.COST_RATIO:
        return ctx.has_role(Role.FINANCE_BP)
    if t == UnitType.LOGISTICS_RATIO:
        return ctx.has_role(Role.LOGISTICS)
    if t == UnitType.DEPT_EXPENSE:
        return ctx.has_role(Role.DEPT_BUDGET) and unit.scope_object_id in ctx.department_ids
    return False


def can_view(db: Session, ctx: ScopeContext, unit: FillingUnit) -> bool:
    """查看：可填报者、审核人、全公司角色；部门负责人可看本部门单位。物流物控只看物流比例单位。"""
    if can_fill(db, ctx, unit) or unit.reviewer_id == ctx.user_id:
        return True
    if ctx.all_company:
        return True
    if ctx.has_role(Role.DEPT_HEAD) and unit_department_id(db, unit) in ctx.department_ids:
        return True
    return False


def ensure_view(db: Session, ctx: ScopeContext, unit: FillingUnit) -> None:
    if not can_view(db, ctx, unit):
        raise Forbidden()


def version_locked(db: Session, version_id: int) -> bool:
    return bool(db.scalar(select(BudgetVersion.locked).where(BudgetVersion.id == version_id)))


def ensure_writable(db: Session, ctx: ScopeContext, unit: FillingUnit) -> None:
    """写入前检查顺序：可查看 → 版本未锁定 → 单位可编辑（已提交 / 已通过拒绝）→ 填报权限（AC-F04-09）。"""
    ensure_view(db, ctx, unit)
    if version_locked(db, unit.version_id):
        raise Conflict(VERSION_LOCKED_MESSAGE, code="version_locked")
    if unit.status not in UnitStatus.EDITABLE:
        raise Conflict(LOCKED_MESSAGE, code="unit_locked")
    if not container_open(db, unit):
        raise Conflict(LOCKED_MESSAGE, code="unit_locked")
    if not can_fill(db, ctx, unit):
        raise Forbidden()


def container_open(db: Session, unit: FillingUnit) -> bool:
    """单位所属编制任务进行中，或所属目标调整进行中（调整单位，G3）。"""
    task = task_of(db, unit)
    if task is not None:
        return task.status == TaskStatus.IN_PROGRESS
    adj = db.get(TargetAdjustment, unit.adjustment_id) if unit.adjustment_id else None
    return adj is not None and adj.status == AdjustmentStatus.IN_PROGRESS


def mark_filling(unit: FillingUnit) -> None:
    """首次保存：未开始 / 已退回 → 填报中（调整单位：已退回 → 调整中）。"""
    if unit.adjustment_id is not None:
        if unit.status == UnitStatus.RETURNED:
            unit.status = UnitStatus.ADJUSTING
    elif unit.status in (UnitStatus.NOT_STARTED, UnitStatus.RETURNED):
        unit.status = UnitStatus.FILLING
    unit.updated_at = clock.now()


def approval_type(unit: FillingUnit) -> str:
    return "adjustment-unit" if unit.adjustment_id else "unit"


def adjustment_summary(db: Session, unit: FillingUnit) -> dict | None:
    if not unit.adjustment_id:
        return None
    adj = db.get(TargetAdjustment, unit.adjustment_id)
    return {"id": adj.id, "year": adj.year, "quarter": adj.quarter, "status": adj.status,
            "name": f"{adj.year} 年第{'一二三四'[adj.quarter - 1]}季度目标调整"}


def last_reject(db: Session, object_type: str, object_id: int) -> ApprovalRecord | None:
    return db.scalar(select(ApprovalRecord).where(ApprovalRecord.object_type == object_type,
                                                  ApprovalRecord.object_id == object_id,
                                                  ApprovalRecord.action == "reject")
                     .order_by(ApprovalRecord.id.desc()).limit(1))


def unit_info(db: Session, ctx: ScopeContext | None, unit: FillingUnit) -> dict:
    """单位摘要（我的填报、填报页页头、任务看板共用）。"""
    task = task_of(db, unit)
    rej = last_reject(db, approval_type(unit), unit.id) if unit.status == UnitStatus.RETURNED else None
    returned_by = user_name(db, rej.approver_id) if rej else None
    editable = False
    if ctx is not None:
        editable = (unit.status in UnitStatus.EDITABLE and can_fill(db, ctx, unit)
                    and not version_locked(db, unit.version_id) and container_open(db, unit))
    filler = db.get(User, unit.filler_id)
    reviewer = db.get(User, unit.reviewer_id)
    overdue = bool(task and is_past_deadline(task) and unit.status not in DONE_STATUSES)
    return {
        "id": unit.id,
        "name": unit.name,
        "unit_type": unit.unit_type,
        "type_label": UnitType.LABELS[unit.unit_type],
        "scope_object_id": unit.scope_object_id,
        "status": unit.status,
        "status_label": UnitStatus.LABELS[unit.status],
        "filler": {"id": filler.id, "name": filler.name} if filler else None,
        "reviewer": {"id": reviewer.id, "name": reviewer.name} if reviewer else None,
        "return_reason": unit.return_reason if unit.status == UnitStatus.RETURNED else None,
        "returned_by": returned_by,
        "returned_at": fmt_dt(rej.created_at) if rej else None,
        "submitted_at": fmt_dt(unit.submitted_at),
        "updated_at": fmt_dt(unit.updated_at) if unit.status != UnitStatus.NOT_STARTED else None,
        "editable": editable,
        "locked": unit.status in (UnitStatus.SUBMITTED, UnitStatus.APPROVED) or version_locked(db, unit.version_id),
        "overdue": overdue,
        "version_id": unit.version_id,
        "task": task_summary(db, task) if task else None,
        "adjustment": adjustment_summary(db, unit),
        "adjust_reason": unit.adjust_reason,
    }


def task_summary(db: Session, task: BudgetTask) -> dict:
    return {"id": task.id, "name": task.name, "year": task.year, "deadline": task.deadline.isoformat(),
            "status": task.status, "status_label": task_status_label(task)}


def task_status_label(task: BudgetTask) -> str:
    if task.status == TaskStatus.IN_PROGRESS and task.ceo_return_reason:
        return "CEO 已退回"
    if task.status == TaskStatus.IN_PROGRESS:
        return "填报中"
    if task.status == TaskStatus.PENDING_CEO:
        return "待 CEO 审批"
    return "已完成"


def overdue_moment(task: BudgetTask) -> datetime:
    """截止日期次日 09:00（Asia/Shanghai）。"""
    return datetime.combine(task.deadline + timedelta(days=1), OVERDUE_AT, tzinfo=TZ)


def is_past_deadline(task: BudgetTask, now: datetime | None = None) -> bool:
    return (now or clock.now()) >= overdue_moment(task)


# ---------------------------------------------------------------------------
# 填报单位候选（AC-F03-05）
# ---------------------------------------------------------------------------
@dataclass
class UnitCandidate:
    unit_type: str
    scope_object_id: int | None
    name: str
    filler: User | None
    reviewer: User | None

    def to_dict(self) -> dict:
        return {"unit_type": self.unit_type, "type_label": UnitType.LABELS[self.unit_type],
                "scope_object_id": self.scope_object_id, "name": self.name,
                "filler": {"id": self.filler.id, "name": self.filler.name} if self.filler else None,
                "reviewer": {"id": self.reviewer.id, "name": self.reviewer.name} if self.reviewer else None}


def _users_with_role(db: Session, role: str) -> list[User]:
    return list(db.scalars(select(User).join(UserRole, UserRole.user_id == User.id)
                           .where(UserRole.role_code == role, User.is_active).order_by(User.id)))


def _scope_ids(db: Session, user_id: int, scope_type: str) -> set[int]:
    return set(db.scalars(select(UserScope.object_id).where(UserScope.user_id == user_id,
                                                            UserScope.scope_type == scope_type)))


def _head_of_user(db: Session, user: User | None) -> User | None:
    if user is None or user.department_id is None:
        return None
    dept = db.get(Department, user.department_id)
    return _head_of_dept(db, dept)


def _head_of_dept(db: Session, dept: Department | None) -> User | None:
    if dept is None or dept.head_user_id is None:
        return None
    head = db.get(User, dept.head_user_id)
    return head if head is not None and head.is_active else None


def unit_candidates(db: Session) -> list[UnitCandidate]:
    """按 AC-F03-05 列出全部可参与的填报单位及其填报人、审核人。"""
    out: list[UnitCandidate] = []
    ops = _users_with_role(db, Role.OPERATIONS)
    ops_scopes = {u.id: (_scope_ids(db, u.id, ScopeType.STORE), _scope_ids(db, u.id, ScopeType.CHANNEL))
                  for u in ops}
    for store in db.scalars(select(Store).where(Store.is_active).order_by(Store.id)):
        filler = next((u for u in ops if store.id in ops_scopes[u.id][0] or store.channel_id in ops_scopes[u.id][1]),
                      None)
        out.append(UnitCandidate(UnitType.PLATFORM, store.id, store.name, filler, _head_of_user(db, filler)))
    b2b_users = _users_with_role(db, Role.B2B)
    b2b_scopes = {u.id: _scope_ids(db, u.id, ScopeType.CUSTOMER) for u in b2b_users}
    dept_ids = list(db.scalars(select(BCustomer.department_id).where(BCustomer.is_active).distinct()))
    for dept in db.scalars(select(Department).where(Department.id.in_(dept_ids)).order_by(Department.sort,
                                                                                          Department.id)):
        customers = set(db.scalars(select(BCustomer.id).where(BCustomer.department_id == dept.id,
                                                             BCustomer.is_active)))
        filler = next((u for u in b2b_users if b2b_scopes[u.id] & customers), None)
        out.append(UnitCandidate(UnitType.B2B, dept.id, f"B端 · {dept.name}", filler, _head_of_dept(db, dept)))
    bp = next(iter(_users_with_role(db, Role.FINANCE_BP)), None)
    out.append(UnitCandidate(UnitType.COST_RATIO, None, "成本比例（财务BP）", bp, _head_of_user(db, bp)))
    lg = next(iter(_users_with_role(db, Role.LOGISTICS)), None)
    out.append(UnitCandidate(UnitType.LOGISTICS_RATIO, None, "物流比例（物流物控）", lg, _head_of_user(db, lg)))
    budget_users = _users_with_role(db, Role.DEPT_BUDGET)
    budget_scopes = {u.id: _scope_ids(db, u.id, ScopeType.DEPARTMENT) for u in budget_users}
    for dept in db.scalars(select(Department).where(Department.is_active).order_by(Department.sort, Department.id)):
        filler = next((u for u in budget_users if dept.id in budget_scopes[u.id]), None)
        out.append(UnitCandidate(UnitType.DEPT_EXPENSE, dept.id, dept.name, filler, _head_of_dept(db, dept)))
    return out


# ---------------------------------------------------------------------------
# 发布任务（API-F03-01、SEQ-F03-01）
# ---------------------------------------------------------------------------
def open_task(db: Session, year: int) -> BudgetTask | None:
    return db.scalar(select(BudgetTask).where(BudgetTask.year == year,
                                              BudgetTask.status.in_((TaskStatus.IN_PROGRESS,
                                                                     TaskStatus.PENDING_CEO))))


def _create_budget_rows(db: Session, version_id: int, year: int, units: list[UnitCandidate]) -> None:
    """建编制稿下全部预算数据行（默认 0），保存时只更新、不新增，便于单元格级乐观锁（DEC-007）。"""
    months = year_months(year)
    categories = list(db.scalars(select(Category.id).order_by(Category.sort, Category.id)))
    store_ids = [u.scope_object_id for u in units if u.unit_type == UnitType.PLATFORM]
    stores = list(db.scalars(select(Store).where(Store.id.in_(store_ids)).order_by(Store.id))) if store_ids else []
    pu_rows = [dict(version_id=version_id, month=m, channel_id=s.channel_id, store_id=s.id, site_id=s.site_id,
                    category_id=c, is_new=is_new)
               for s in stores for m in months for c in categories for is_new in (True, False)]
    # 比例：全部启用店铺的渠道 × 站点（成本比例 / 物流比例页按基础数据列出）
    pairs = sorted(set(db.execute(select(Store.channel_id, Store.site_id).where(Store.is_active)).all())
                   | {(s.channel_id, s.site_id) for s in stores})
    ccr_rows = [dict(version_id=version_id, month=m, channel_id=ch, site_id=si, category_id=c)
                for ch, si in pairs for m in months for c in categories]
    csr_rows = [dict(version_id=version_id, month=m, channel_id=ch, site_id=si) for ch, si in pairs for m in months]
    b2b_depts = [u.scope_object_id for u in units if u.unit_type == UnitType.B2B]
    customers = list(db.scalars(select(BCustomer.id).where(BCustomer.department_id.in_(b2b_depts),
                                                           BCustomer.is_active).order_by(BCustomer.id))) \
        if b2b_depts else []
    b2b_rows = [dict(version_id=version_id, month=m, customer_id=c) for c in customers for m in months]
    accounts = list(db.scalars(select(BudgetAccount.id).where(BudgetAccount.is_dept_expense, BudgetAccount.is_active)
                               .order_by(BudgetAccount.sort, BudgetAccount.id)))
    dept_rows = [dict(version_id=version_id, month=m, department_id=u.scope_object_id, account_id=a)
                 for u in units if u.unit_type == UnitType.DEPT_EXPENSE for a in accounts for m in months]
    opl_rows = [dict(version_id=version_id, month=m, item=item) for item in OtherPlItem.LABELS for m in months]
    for model, rows in ((PlatformUnit, pu_rows), (ChannelCategoryRatio, ccr_rows), (ChannelSiteRatio, csr_rows),
                        (B2bUnit, b2b_rows), (DeptExpense, dept_rows), (CompanyOtherPl, opl_rows)):
        if rows:
            db.execute(insert(model), rows)


def publish_task(db: Session, actor: CurrentUser, settings, *, year: int | None, deadline: date | None,
                 units: list[dict] | None, request=None) -> dict:
    if not year:
        raise ValidationFailed("请选择预算年度", code="year_required")
    if deadline is None:
        raise ValidationFailed("请选择截止日期", code="deadline_required")
    today = clock.today()
    if deadline <= today:
        raise ValidationFailed(f"截止日期须晚于今天（{today.isoformat()}）", code="deadline_past")
    existing = open_task(db, year)
    if existing is not None:
        raise Conflict(f"{year} 年度已有未完成 CEO 审批的编制任务「{existing.name}」，不能再发布同年度任务。",
                       code="task_exists", details={"task_name": existing.name, "task_id": existing.id})
    candidates = unit_candidates(db)
    if units is not None:
        wanted = {(u.get("unit_type"), u.get("scope_object_id")) for u in units}
        candidates = [c for c in candidates if (c.unit_type, c.scope_object_id) in wanted]
    if not candidates:
        raise ValidationFailed("请至少选择 1 个参与填报单位", code="units_required")
    missing = [c.name for c in candidates if c.filler is None or c.reviewer is None]
    if missing:
        raise ValidationFailed(f"以下填报单位缺少填报人或审核人，未发布：{'、'.join(missing)}",
                               code="unit_missing_people", details={"units": missing})
    now = clock.now()
    version_no = (db.scalar(select(func.max(BudgetVersion.version_no))
                            .where(BudgetVersion.year == year, BudgetVersion.type == VersionType.DRAFT)) or 0) + 1
    version = BudgetVersion(year=year, type=VersionType.DRAFT, version_no=version_no,
                            name=f"{year} 年度预算编制稿", created_by=actor.user.id, created_at=now)
    db.add(version)
    db.flush()
    task = BudgetTask(name=f"{year} 年度预算编制", year=year, deadline=deadline, status=TaskStatus.IN_PROGRESS,
                      version_id=version.id, created_by=actor.user.id, created_at=now)
    db.add(task)
    db.flush()
    for c in candidates:
        db.add(FillingUnit(task_id=task.id, version_id=version.id, unit_type=c.unit_type,
                           scope_object_id=c.scope_object_id, name=c.name, filler_id=c.filler.id,
                           reviewer_id=c.reviewer.id, status=UnitStatus.NOT_STARTED, updated_at=now))
    db.flush()
    _create_budget_rows(db, version.id, year, candidates)
    write_audit(db, action="task.publish", object_type="budget_task", object_id=task.id, actor=actor,
                request=request, after={"name": task.name, "year": year, "deadline": deadline,
                                        "units": [c.name for c in candidates]})
    filler_ids = sorted({c.filler.id for c in candidates})
    for uid in filler_ids:
        notify(db, biz_type="task_published", biz_id=task.id, user_ids=[uid],
               title=f"【预算管理平台】{year} 年度预算编制已发布",
               name=task.name, object_name=f"截止日期 {deadline.isoformat()}，请在截止前完成填报",
               period=f"{year} 年度", link=app_link(settings, "/filling"))
    return {"task": task_row(db, task), "unit_count": len(candidates), "filler_count": len(filler_ids)}


# ---------------------------------------------------------------------------
# 列表与进度（API-F03-01、API-F03-02）
# ---------------------------------------------------------------------------
def submit_stats(db: Session, task_id: int) -> tuple[int, int]:
    """DEC-026：（已提交 + 已通过）单位数、全部单位数（工作台与看板共用口径）。"""
    total, done = db.execute(
        select(func.count(), func.count().filter(FillingUnit.status.in_(DONE_STATUSES)))
        .where(FillingUnit.task_id == task_id)).one()
    return done, total


def rate_str(done: int, total: int) -> str | None:
    if not total:
        return None
    return str((Decimal(done) * 100 / Decimal(total)).quantize(Decimal("0.1")))


def task_row(db: Session, task: BudgetTask) -> dict:
    done, total = submit_stats(db, task.id)
    return {**task_summary(db, task), "unit_count": total, "submitted_count": done,
            "submit_rate": rate_str(done, total), "created_by": user_name(db, task.created_by),
            "created_at": fmt_dt(task.created_at), "ceo_return_reason": task.ceo_return_reason}


def list_tasks(db: Session) -> list[dict]:
    tasks = db.scalars(select(BudgetTask).order_by(BudgetTask.created_at.desc(), BudgetTask.id.desc()))
    return [task_row(db, t) for t in tasks]


def _overdue_notice(db: Session, task: BudgetTask) -> tuple[list[int], datetime | None]:
    row = db.scalar(select(AuditLog).where(AuditLog.object_type == "budget_task",
                                           AuditLog.object_id == str(task.id),
                                           AuditLog.action == "task.overdue_notified")
                    .order_by(AuditLog.id.desc()).limit(1))
    if row is None:
        return [], None
    return list((row.after or {}).get("unit_ids", [])), task.overdue_notified_at


def task_progress(db: Session, ctx: ScopeContext, task_id: int) -> dict:
    task = db.get(BudgetTask, task_id)
    if task is None:
        raise NotFound("编制任务不存在")
    units = list(db.scalars(select(FillingUnit).where(FillingUnit.task_id == task.id).order_by(FillingUnit.id)))
    units.sort(key=lambda u: (UNIT_TYPE_ORDER.index(u.unit_type), u.id))
    notified_ids, notified_at = _overdue_notice(db, task)
    past = is_past_deadline(task)
    rows = []
    counts = {s: 0 for s in (UnitStatus.NOT_STARTED, UnitStatus.FILLING, UnitStatus.SUBMITTED,
                             UnitStatus.RETURNED, UnitStatus.APPROVED)}
    for u in units:
        counts[u.status] = counts.get(u.status, 0) + 1
        info = unit_info(db, None, u)
        rej = last_reject(db, "unit", u.id) if u.status == UnitStatus.RETURNED else None
        rows.append({**info, "overdue": past and u.status not in DONE_STATUSES,
                     "reminded": u.id in notified_ids,
                     "return_reason_display": f"{user_name(db, rej.approver_id)}：{u.return_reason}"
                     if rej and u.return_reason else None})
    done, total = submit_stats(db, task.id)
    ceo_rej = last_reject(db, "task", task.id) if task.ceo_return_reason else None
    return {
        "task": task_row(db, task),
        "deadline_passed": past,
        "overdue_notified_at": fmt_dt(notified_at),
        "overdue_notified_count": len(notified_ids),
        "submit_rate": rate_str(done, total),
        "submitted_count": done,
        "unit_count": total,
        "counts": counts,
        "ceo_return": {"reason": task.ceo_return_reason, "by": user_name(db, ceo_rej.approver_id) if ceo_rej else None,
                       "at": fmt_dt(ceo_rej.created_at) if ceo_rej else None} if task.ceo_return_reason else None,
        "can_manage": ctx.has_role(Role.FINANCE_HEAD),
        "units": rows,
    }


# ---------------------------------------------------------------------------
# 逾期提醒（AC-F03-04，调度器每日 09:00）
# ---------------------------------------------------------------------------
@register_overdue_hook
def send_overdue_reminders(db: Session, now: datetime) -> int:
    """截止次日 09:00 起，对每个进行中任务只提醒一次：状态不是已提交或已通过的单位，向填报人及其部门负责人各发一条。"""
    from app.config import get_settings

    settings = get_settings()
    sent = 0
    tasks = db.scalars(select(BudgetTask).where(BudgetTask.status == TaskStatus.IN_PROGRESS,
                                                BudgetTask.overdue_notified_at.is_(None)))
    for task in tasks:
        if not is_past_deadline(task, now):
            continue
        late = list(db.scalars(select(FillingUnit).where(FillingUnit.task_id == task.id,
                                                         FillingUnit.status.not_in(DONE_STATUSES))
                               .order_by(FillingUnit.id)))
        for u in late:
            notify(db, biz_type="task_overdue", biz_id=u.id, user_ids=[u.filler_id, u.reviewer_id],
                   title=f"【预算管理平台】{task.name}已逾期", name=task.name,
                   object_name=f"填报单位：{u.name}，截止日期 {task.deadline.isoformat()}",
                   period=f"{task.year} 年度", link=app_link(settings, "/filling"))
        task.overdue_notified_at = now
        write_audit(db, action="task.overdue_notified", object_type="budget_task", object_id=task.id,
                    actor_name="system-scheduler", after={"unit_ids": [u.id for u in late], "at": now})
        sent += len(late)
    db.flush()
    return sent


# ---------------------------------------------------------------------------
# 提交 CEO（API-F03-03）与 CEO 退回后退回指定单位（AC-F07-06）
# ---------------------------------------------------------------------------
def submit_to_ceo(db: Session, actor: CurrentUser, settings, task_id: int, request=None) -> dict:
    task = db.scalar(select(BudgetTask).where(BudgetTask.id == task_id).with_for_update())
    if task is None:
        raise NotFound("编制任务不存在")
    if task.status != TaskStatus.IN_PROGRESS:
        raise Conflict("状态已变化，请刷新", code="status_changed")
    pending = list(db.scalars(select(FillingUnit).where(FillingUnit.task_id == task.id,
                                                        FillingUnit.status != UnitStatus.APPROVED)
                              .order_by(FillingUnit.id)))
    if pending:
        pending.sort(key=lambda u: (UNIT_TYPE_ORDER.index(u.unit_type), u.id))
        raise ValidationFailed(f"还有 {len(pending)} 个填报单位未通过部门审核，不能提交 CEO 审批",
                               code="units_not_approved",
                               details={"units": [{"id": u.id, "name": u.name, "status": u.status,
                                                   "status_label": UnitStatus.LABELS[u.status]}
                                                  for u in pending]})
    before = task.status
    task.status = TaskStatus.PENDING_CEO
    write_audit(db, action="task.submit_to_ceo", object_type="budget_task", object_id=task.id, actor=actor,
                request=request, before={"status": before, "ceo_return_reason": task.ceo_return_reason},
                after={"status": task.status})
    task.ceo_return_reason = None
    ceo_ids = [u.id for u in _users_with_role(db, Role.CEO)]
    notify(db, biz_type="task_pending_ceo", biz_id=task.id, user_ids=ceo_ids,
           title="【预算管理平台】全公司预算待你审批", name=task.name, object_name="全公司预算",
           period=f"{task.year} 年度", link=app_link(settings, f"/approvals/task/{task.id}"))
    db.flush()
    return task_row(db, task)


def return_unit_to_filler(db: Session, actor: CurrentUser, settings, task_id: int, unit_id: int,
                          reason: str | None, request=None) -> dict:
    """CEO 退回后，财务负责人把指定（已通过）单位退回其填报人：已通过 → 已退回，解锁并通知（AC-F07-06）。"""
    text = require_reason(reason)
    task = db.get(BudgetTask, task_id)
    if task is None:
        raise NotFound("编制任务不存在")
    if task.status != TaskStatus.IN_PROGRESS or not task.ceo_return_reason:
        raise Conflict("只有 CEO 退回后才能把单位退回给填报人", code="not_ceo_returned")
    unit = get_unit(db, unit_id, lock=True)
    if unit.task_id != task.id:
        raise NotFound("填报单位不存在")
    if unit.status != UnitStatus.APPROVED:
        raise Conflict("状态已变化，请刷新", code="status_changed")
    unit.status = UnitStatus.RETURNED
    unit.return_reason = text
    unit.updated_at = clock.now()
    db.add(ApprovalRecord(object_type="unit", object_id=unit.id, level="finance_head", action="reject",
                          reason=text, approver_id=actor.user.id, created_at=clock.now()))
    write_audit(db, action="unit.return_by_finance_head", object_type="filling_unit", object_id=unit.id,
                actor=actor, request=request, before={"status": UnitStatus.APPROVED},
                after={"status": UnitStatus.RETURNED, "reason": text})
    notify(db, biz_type="unit_returned", biz_id=unit.id, user_ids=[unit.filler_id],
           title="【预算管理平台】你的填报被退回", name=task.name, object_name=unit.name,
           period=f"{task.year} 年度", link=app_link(settings, fill_path(unit)))
    db.flush()
    return unit_info(db, None, unit)


def fill_path(unit: FillingUnit) -> str:
    return {UnitType.PLATFORM: f"/filling/platform/{unit.id}", UnitType.B2B: f"/filling/b2b/{unit.id}",
            UnitType.COST_RATIO: f"/filling/cost/{unit.id}", UnitType.LOGISTICS_RATIO: f"/filling/logistics/{unit.id}",
            UnitType.DEPT_EXPENSE: f"/dept-expense?unitId={unit.id}"}[unit.unit_type]


def month_keys(year: int) -> list[str]:
    return [fmt_month(m) for m in year_months(year)]


def ensure_task_reader(ctx: ScopeContext) -> None:
    if not ctx.has_role(Role.FINANCE_HEAD, Role.CEO):
        raise Forbidden()

