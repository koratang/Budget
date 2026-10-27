"""季度目标调整（DATA-F08-03；AC-F08-01~04，DEC-022「4A」，SEQ-F08-01）。

调整单位（FillingUnit.adjustment_id 非空）：调整中 → 已提交 → 部门已通过 → 已通过；部门负责人 / 财务负责人可退回。
调整：调整进行中 →（最后一个单位经财务负责人通过，自动）待CEO终审 →（CEO 整次通过）已生效，调整稿转为
调整后目标 Vn（locked）；CEO 退回 → 调整进行中。

跨组审批接口（第二期分工「跨组接口」）：本模块同时服务 type = adjustment-unit 与 adjustment。
pending_items 返回两种类型的事项；detail / approve / reject 可传 obj_type 指明类型，不传时按角色判断
（CEO 处理整次调整，部门负责人与财务负责人处理调整单位）。服务函数只 flush，由调用方路由 commit。
填报表格（G2）在调整模式下保存单元格前调用 ensure_month_adjustable()，提交调用 submit_unit()。
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select, update

from app.calc.periods import fmt_month, quarter_of
from app.core.clock import clock
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.models import ApprovalRecord, BudgetVersion, FillingUnit, TargetAdjustment, User
from app.models.enums import AdjustmentStatus, Role, UnitStatus, UnitType, VersionType
from app.services.versions import (Actor, actual_months, as_actor, audit, copy_version_rows, current_target,
                                   ensure_complete, fmt_dt, notify, plan_units, users_with_role, version_label)

TYPE_UNIT = "adjustment-unit"
TYPE_ADJUSTMENT = "adjustment"
ADJUST_REASON_REQUIRED = "请填写调整原因"
REJECT_REASON_REQUIRED = "请填写退回原因"
MONTH_LOCKED = "该月已导入实际，不能调整"
STATE_CHANGED = "状态已变化，请刷新"

UNIT_STEP = {
    UnitStatus.ADJUSTING: "待提交",
    UnitStatus.SUBMITTED: "部门负责人审核",
    UnitStatus.DEPT_APPROVED: "财务负责人审核",
    UnitStatus.APPROVED: "已通过，等待 CEO 整次终审",
    UnitStatus.RETURNED: "已退回，待修改后重新提交",
}


def _link(path: str) -> str:
    from app.config import get_settings
    return f"{get_settings().APP_BASE_URL.rstrip('/')}{path}"


# ---------------------------------------------------------------------------
# 发起（API-F08-02）
# ---------------------------------------------------------------------------
def block_reason(db, year: int, quarter: int) -> tuple[str, str] | None:
    """不能发起时返回（代码, 原因）。"""
    done = db.scalar(select(TargetAdjustment).where(TargetAdjustment.year == year,
                                                    TargetAdjustment.quarter == quarter,
                                                    TargetAdjustment.status == AdjustmentStatus.EFFECTIVE))
    if done is not None:
        v = db.get(BudgetVersion, done.result_version_id) if done.result_version_id else None
        label = version_label(v) if v else "调整后目标"
        when = done.effective_at.astimezone(clock.now().tzinfo).date().isoformat() if done.effective_at else ""
        nxt = date(year + (quarter == 4), 1 if quarter == 4 else quarter * 3 + 1, 1).isoformat()
        return ("adjustment_quarter_used",
                f"本季度已有一次经 CEO 审批通过的目标调整（{label}，{when}），{nxt} 起可发起下季度调整")
    running = db.scalar(select(TargetAdjustment).where(
        TargetAdjustment.year == year,
        TargetAdjustment.status.in_((AdjustmentStatus.IN_PROGRESS, AdjustmentStatus.PENDING_CEO))))
    if running is not None:
        return ("adjustment_in_progress",
                f"{running.year} Q{running.quarter} 目标调整正在审批中，审批结束前不能再发起")
    if current_target(db, year) is None:
        return ("no_target", f"{year} 年度还没有年初原始目标，不能发起目标调整")
    return None


def start_adjustment(db, user, *, today: date) -> TargetAdjustment:
    actor = as_actor(db, user)
    if not actor.has_role(Role.FINANCE_HEAD):
        raise Forbidden()
    year, quarter = today.year, quarter_of(today)
    blocked = block_reason(db, year, quarter)
    if blocked:
        raise Conflict(blocked[1], code=blocked[0])
    units = plan_units(db)
    ensure_complete(units)
    source = current_target(db, year)
    draft = BudgetVersion(year=year, type=VersionType.ADJUSTMENT_DRAFT, version_no=quarter, quarter=quarter,
                          name=f"{year} Q{quarter} 目标调整稿", source_version_id=source.id, created_by=actor.id)
    db.add(draft)
    db.flush()
    copy_version_rows(db, source.id, draft.id)
    adj = TargetAdjustment(year=year, quarter=quarter, status=AdjustmentStatus.IN_PROGRESS,
                           draft_version_id=draft.id, initiated_by=actor.id)
    db.add(adj)
    db.flush()
    for p in units:
        db.add(FillingUnit(adjustment_id=adj.id, version_id=draft.id, unit_type=p.unit_type,
                           scope_object_id=p.scope_object_id, name=p.name, filler_id=p.filler.id,
                           reviewer_id=p.reviewer.id, status=UnitStatus.ADJUSTING))
    db.flush()
    audit(db, actor, action="adjustment_started", object_type="target_adjustment", object_id=adj.id,
          after={"year": year, "quarter": quarter, "source_version": version_label(source),
                 "draft_version_id": draft.id, "units": len(units)})
    notify(db, biz_type="adjustment_started", biz_id=adj.id, users=[p.filler for p in units],
           title="【目标调整】", name=f"{year} Q{quarter} 目标调整", object_name="请在填报表格调整模式中修改并提交",
           period=f"{year} Q{quarter}", link=_link("/versions"))
    return adj


# ---------------------------------------------------------------------------
# 调整模式编辑与提交（填报表格调用）
# ---------------------------------------------------------------------------
def adjustable_months(db, year: int) -> list[date]:
    done = actual_months(db, year)
    return [date(year, m, 1) for m in range(1, 13) if date(year, m, 1) not in done]


def ensure_month_adjustable(db, unit: FillingUnit, month: date) -> None:
    """AC-F08-02：调整单位只允许修改尚未导入金蝶实际的月份，否则 422「该月已导入实际，不能调整」。"""
    if unit.adjustment_id is None:
        return
    if month in actual_months(db, month.year):
        raise ValidationFailed(MONTH_LOCKED, code="month_has_actual", details={"month": fmt_month(month)})


def _get_unit(db, unit_id: int, *, lock: bool = False) -> FillingUnit:
    q = select(FillingUnit).where(FillingUnit.id == unit_id, FillingUnit.adjustment_id.is_not(None))
    unit = db.scalar(q.with_for_update() if lock else q)
    if unit is None:
        raise NotFound("调整单位不存在")
    return unit


def _transition(db, unit: FillingUnit, expect: tuple[str, ...], **values) -> None:
    """状态条件更新：影响行数为 0 返回「状态已变化，请刷新」。"""
    res = db.execute(update(FillingUnit).where(FillingUnit.id == unit.id, FillingUnit.status.in_(expect))
                     .values(updated_at=clock.now(), **values))
    if res.rowcount != 1:
        raise Conflict(STATE_CHANGED, code="state_changed")
    db.refresh(unit)


def submit_unit(db, user, unit_id: int, reason: str | None) -> FillingUnit:
    """调整单位提交（调整原因必填，AC-F08-03）：调整中 / 已退回 → 已提交，通知部门负责人。"""
    actor = as_actor(db, user)
    unit = _get_unit(db, unit_id, lock=True)
    if unit.filler_id != actor.id:
        raise Forbidden()
    adj = db.get(TargetAdjustment, unit.adjustment_id)
    if adj.status != AdjustmentStatus.IN_PROGRESS:
        raise Conflict("目标调整不在进行中，不能提交", code="adjustment_closed")
    if not (reason or "").strip():
        raise ValidationFailed(ADJUST_REASON_REQUIRED, code="adjust_reason_required")
    before = unit.status
    _transition(db, unit, (UnitStatus.ADJUSTING, UnitStatus.RETURNED), status=UnitStatus.SUBMITTED,
                adjust_reason=reason.strip(), submitted_at=clock.now(), return_reason=None)
    audit(db, actor, action="adjustment_unit_submitted", object_type="filling_unit", object_id=unit.id,
          before={"status": before}, after={"status": unit.status, "adjust_reason": unit.adjust_reason})
    notify(db, biz_type="adj_unit_submitted", biz_id=unit.id, users=[db.get(User, unit.reviewer_id)],
           title="【待审批】目标调整", name=f"{adj.year} Q{adj.quarter} 目标调整", object_name=unit.name,
           period=f"{adj.year} Q{adj.quarter}", link=_link(f"/approvals/{TYPE_UNIT}/{unit.id}"))
    return unit


# ---------------------------------------------------------------------------
# 审批（跨组接口）
# ---------------------------------------------------------------------------
def _resolve_type(actor: Actor, obj_type: str | None) -> str:
    if obj_type in (TYPE_UNIT, TYPE_ADJUSTMENT):
        return obj_type
    if actor.has_role(Role.CEO) and not actor.has_role(Role.FINANCE_HEAD, Role.DEPT_HEAD):
        return TYPE_ADJUSTMENT
    return TYPE_UNIT


def _unit_level(actor: Actor, unit: FillingUnit) -> str | None:
    """当前用户对该调整单位所处环节的审批级别。"""
    if unit.status == UnitStatus.SUBMITTED and unit.reviewer_id == actor.id:
        return "dept_head"
    if unit.status == UnitStatus.DEPT_APPROVED and actor.has_role(Role.FINANCE_HEAD):
        return "finance_head"
    return None


def pending_items(db, user) -> list[dict]:
    actor = as_actor(db, user)
    items: list[dict] = []
    # 部门负责人环节以单位的审核人为准；财务负责人环节对全部「部门已通过」单位
    conds = [(FillingUnit.status == UnitStatus.SUBMITTED) & (FillingUnit.reviewer_id == actor.id)]
    if actor.has_role(Role.FINANCE_HEAD):
        conds.append(FillingUnit.status == UnitStatus.DEPT_APPROVED)
    rows = db.execute(select(FillingUnit, TargetAdjustment).join(TargetAdjustment,
                                                                 TargetAdjustment.id == FillingUnit.adjustment_id)
                      .where(or_(*conds), TargetAdjustment.status == AdjustmentStatus.IN_PROGRESS)
                      .order_by(FillingUnit.submitted_at, FillingUnit.id)).all()
    for unit, adj in rows:
        filler = db.get(User, unit.filler_id)
        prev = (f"{filler.name} 已提交" if unit.status == UnitStatus.SUBMITTED
                else f"部门负责人 {db.get(User, unit.reviewer_id).name} 已通过")
        step = "部门负责人审核" if unit.status == UnitStatus.SUBMITTED else "财务负责人审核"
        items.append({"type": TYPE_UNIT, "id": unit.id, "title": f"{adj.year} Q{adj.quarter} 目标调整 · {unit.name}",
                      "kind_label": "目标调整（单位）", "prev_step": prev, "step": step, "submitter": filler.name,
                      "submitted_at": unit.submitted_at.isoformat() if unit.submitted_at else None,
                      "link": f"/approvals/{TYPE_UNIT}/{unit.id}"})
    if actor.has_role(Role.CEO):
        for adj in db.scalars(select(TargetAdjustment).where(TargetAdjustment.status == AdjustmentStatus.PENDING_CEO)
                              .order_by(TargetAdjustment.id)):
            last = db.scalar(select(func.max(ApprovalRecord.created_at)).where(
                ApprovalRecord.object_type == TYPE_UNIT,
                ApprovalRecord.object_id.in_(select(FillingUnit.id).where(FillingUnit.adjustment_id == adj.id))))
            items.append({"type": TYPE_ADJUSTMENT, "id": adj.id, "title": f"{adj.year} Q{adj.quarter} 目标调整（整次终审）",
                          "kind_label": "目标调整（CEO 终审）", "prev_step": "全部单位已经财务负责人通过",
                          "step": "CEO 终审", "submitter": db.get(User, adj.initiated_by).name if adj.initiated_by else None,
                          "submitted_at": last.isoformat() if last else None,
                          "link": f"/approvals/{TYPE_ADJUSTMENT}/{adj.id}"})
    return items


def _records(db, obj_type: str, obj_id: int) -> list[dict]:
    rows = db.execute(select(ApprovalRecord, User.name).join(User, User.id == ApprovalRecord.approver_id)
                      .where(ApprovalRecord.object_type == obj_type, ApprovalRecord.object_id == obj_id)
                      .order_by(ApprovalRecord.id)).all()
    return [{"level": r.level, "action": r.action, "reason": r.reason, "approver_name": name,
             "at": fmt_dt(r.created_at)} for r, name in rows]


def unit_view(db, unit: FillingUnit) -> dict:
    filler = db.get(User, unit.filler_id)
    reviewer = db.get(User, unit.reviewer_id)
    return {"id": unit.id, "name": unit.name, "unit_type": unit.unit_type,
            "unit_type_label": UnitType.LABELS[unit.unit_type], "scope_object_id": unit.scope_object_id,
            "status": unit.status, "status_label": UnitStatus.LABELS[unit.status],
            "step": UNIT_STEP.get(unit.status, ""), "filler_id": unit.filler_id, "filler_name": filler.name,
            "reviewer_name": reviewer.name, "adjust_reason": unit.adjust_reason, "return_reason": unit.return_reason,
            "submitted_at": fmt_dt(unit.submitted_at), "version_id": unit.version_id}


def adjustment_view(db, adj: TargetAdjustment) -> dict:
    units = db.scalars(select(FillingUnit).where(FillingUnit.adjustment_id == adj.id)
                       .order_by(FillingUnit.id)).all()
    initiator = db.get(User, adj.initiated_by) if adj.initiated_by else None
    result = db.get(BudgetVersion, adj.result_version_id) if adj.result_version_id else None
    submitted = sum(u.status in (UnitStatus.SUBMITTED, UnitStatus.DEPT_APPROVED, UnitStatus.APPROVED) for u in units)
    dept_ok = sum(u.status in (UnitStatus.DEPT_APPROVED, UnitStatus.APPROVED) for u in units)
    fin_ok = sum(u.status == UnitStatus.APPROVED for u in units)
    months = adjustable_months(db, adj.year)
    return {
        "id": adj.id, "year": adj.year, "quarter": adj.quarter, "status": adj.status,
        "status_label": AdjustmentStatus.LABELS[adj.status],
        "initiated_by_name": initiator.name if initiator else None,
        "initiated_at": fmt_dt(adj.created_at), "ceo_return_reason": adj.ceo_return_reason,
        "effective_at": fmt_dt(adj.effective_at), "draft_version_id": adj.draft_version_id,
        "result_version": version_label(result) if result else None,
        "adjustable_months": [fmt_month(m) for m in months],
        "progress": {"total": len(units), "submitted": submitted, "dept_approved": dept_ok, "finance_approved": fin_ok},
        "units": [unit_view(db, u) for u in units],
        "ceo_records": _records(db, TYPE_ADJUSTMENT, adj.id),
    }


def detail(db, user, obj_id: int, obj_type: str | None = None) -> dict:
    actor = as_actor(db, user)
    kind = _resolve_type(actor, obj_type)
    if kind == TYPE_ADJUSTMENT:
        adj = db.get(TargetAdjustment, obj_id)
        if adj is None:
            raise NotFound("目标调整不存在")
        if not actor.has_role(Role.CEO, Role.FINANCE_HEAD):
            raise Forbidden()
        view = adjustment_view(db, adj)
        source = db.get(BudgetVersion, db.get(BudgetVersion, adj.draft_version_id).source_version_id)
        view.update(type=TYPE_ADJUSTMENT, source_version=version_label(source), source_version_id=source.id,
                    can_act=adj.status == AdjustmentStatus.PENDING_CEO and actor.has_role(Role.CEO),
                    reasons=[{"unit": u["name"], "reason": u["adjust_reason"]} for u in view["units"]
                             if u["adjust_reason"]])
        return view
    unit = _get_unit(db, obj_id)
    adj = db.get(TargetAdjustment, unit.adjustment_id)
    if not (actor.has_role(Role.FINANCE_HEAD, Role.CEO) or unit.reviewer_id == actor.id
            or unit.filler_id == actor.id):
        raise Forbidden()
    view = unit_view(db, unit)
    view.update(type=TYPE_UNIT, adjustment_id=adj.id, year=adj.year, quarter=adj.quarter,
                records=_records(db, TYPE_UNIT, unit.id),
                can_act=adj.status == AdjustmentStatus.IN_PROGRESS and _unit_level(actor, unit) is not None)
    return view


def _record(db, actor: Actor, obj_type: str, obj_id: int, level: str, action: str, reason: str | None = None):
    db.add(ApprovalRecord(object_type=obj_type, object_id=obj_id, level=level, action=action, reason=reason,
                          approver_id=actor.id))
    db.flush()


def approve(db, user, obj_id: int, obj_type: str | None = None) -> dict:
    actor = as_actor(db, user)
    if _resolve_type(actor, obj_type) == TYPE_ADJUSTMENT:
        return _approve_adjustment(db, actor, obj_id)
    return _approve_unit(db, actor, obj_id)


def reject(db, user, obj_id: int, reason: str, obj_type: str | None = None) -> dict:
    actor = as_actor(db, user)
    if not (reason or "").strip():
        raise ValidationFailed(REJECT_REASON_REQUIRED, code="reason_required")
    reason = reason.strip()
    if _resolve_type(actor, obj_type) == TYPE_ADJUSTMENT:
        return _reject_adjustment(db, actor, obj_id, reason)
    return _reject_unit(db, actor, obj_id, reason)


def _approve_unit(db, actor: Actor, unit_id: int) -> dict:
    unit = _get_unit(db, unit_id)
    adj = db.scalar(select(TargetAdjustment).where(TargetAdjustment.id == unit.adjustment_id).with_for_update())
    if adj.status != AdjustmentStatus.IN_PROGRESS:
        raise Conflict(STATE_CHANGED, code="state_changed")
    level = _unit_level(actor, unit)
    if level is None:
        if unit.reviewer_id == actor.id or actor.has_role(Role.FINANCE_HEAD):
            raise Conflict(STATE_CHANGED, code="state_changed")
        raise Forbidden()
    before = unit.status
    if level == "dept_head":
        _transition(db, unit, (UnitStatus.SUBMITTED,), status=UnitStatus.DEPT_APPROVED)
    else:
        _transition(db, unit, (UnitStatus.DEPT_APPROVED,), status=UnitStatus.APPROVED)
    _record(db, actor, TYPE_UNIT, unit.id, level, "approve")
    audit(db, actor, action="adjustment_unit_approved", object_type="filling_unit", object_id=unit.id,
          before={"status": before}, after={"status": unit.status, "level": level})
    if level == "finance_head":
        # 调整行已加锁：统计全部单位，最后一个通过时转待CEO终审并通知 CEO（DEC-022）
        open_count = db.scalar(select(func.count()).select_from(FillingUnit).where(
            FillingUnit.adjustment_id == adj.id, FillingUnit.status != UnitStatus.APPROVED))
        if open_count == 0:
            adj.status = AdjustmentStatus.PENDING_CEO
            db.flush()
            audit(db, actor, action="adjustment_pending_ceo", object_type="target_adjustment", object_id=adj.id,
                  before={"status": AdjustmentStatus.IN_PROGRESS}, after={"status": adj.status})
            notify(db, biz_type="adj_pending_ceo", biz_id=adj.id, users=users_with_role(db, Role.CEO),
                   title="【待审批】目标调整终审", name=f"{adj.year} Q{adj.quarter} 目标调整",
                   object_name="全部单位已通过", period=f"{adj.year} Q{adj.quarter}",
                   link=_link(f"/approvals/{TYPE_ADJUSTMENT}/{adj.id}"))
    return {"type": TYPE_UNIT, "id": unit.id, "status": unit.status, "adjustment_status": adj.status}


def _reject_unit(db, actor: Actor, unit_id: int, reason: str) -> dict:
    unit = _get_unit(db, unit_id)
    adj = db.scalar(select(TargetAdjustment).where(TargetAdjustment.id == unit.adjustment_id).with_for_update())
    if adj.status != AdjustmentStatus.IN_PROGRESS:
        raise Conflict(STATE_CHANGED, code="state_changed")
    level = _unit_level(actor, unit)
    expect: tuple[str, ...]
    if level == "dept_head":
        expect = (UnitStatus.SUBMITTED,)
    elif level == "finance_head":
        expect = (UnitStatus.DEPT_APPROVED,)
    elif unit.status == UnitStatus.APPROVED and actor.has_role(Role.FINANCE_HEAD):
        # CEO 退回后由财务负责人指定单位退回
        level, expect = "finance_head", (UnitStatus.APPROVED,)
    else:
        if unit.reviewer_id == actor.id or actor.has_role(Role.FINANCE_HEAD):
            raise Conflict(STATE_CHANGED, code="state_changed")
        raise Forbidden()
    before = unit.status
    _transition(db, unit, expect, status=UnitStatus.RETURNED, return_reason=reason)
    _record(db, actor, TYPE_UNIT, unit.id, level, "reject", reason)
    audit(db, actor, action="adjustment_unit_returned", object_type="filling_unit", object_id=unit.id,
          before={"status": before}, after={"status": unit.status, "reason": reason, "level": level})
    notify(db, biz_type="adj_unit_returned", biz_id=unit.id, users=[db.get(User, unit.filler_id)],
           title="【已退回】目标调整", name=f"{adj.year} Q{adj.quarter} 目标调整", object_name=unit.name,
           period=f"{adj.year} Q{adj.quarter}", link=_link("/versions"))
    return {"type": TYPE_UNIT, "id": unit.id, "status": unit.status}


def _approve_adjustment(db, actor: Actor, adj_id: int) -> dict:
    if not actor.has_role(Role.CEO):
        raise Forbidden()
    adj = db.scalar(select(TargetAdjustment).where(TargetAdjustment.id == adj_id).with_for_update())
    if adj is None:
        raise NotFound("目标调整不存在")
    if adj.status != AdjustmentStatus.PENDING_CEO:
        raise Conflict(STATE_CHANGED, code="state_changed")
    units = db.scalars(select(FillingUnit).where(FillingUnit.adjustment_id == adj.id).order_by(FillingUnit.id)).all()
    if any(u.status != UnitStatus.APPROVED for u in units):
        raise Conflict("仍有调整单位未经财务负责人通过", code="units_not_approved")
    draft = db.get(BudgetVersion, adj.draft_version_id)
    next_no = (db.scalar(select(func.max(BudgetVersion.version_no)).where(
        BudgetVersion.year == adj.year,
        BudgetVersion.type.in_((VersionType.ORIGINAL_TARGET, VersionType.ADJUSTED_TARGET)))) or 0) + 1
    now = clock.now()
    reasons = "；".join(f"{u.name}：{u.adjust_reason}" for u in units if u.adjust_reason)
    draft.type = VersionType.ADJUSTED_TARGET
    draft.version_no = next_no
    draft.name = f"{adj.year} 调整后目标 V{next_no}"
    draft.adjust_reason = reasons
    draft.approved_by = actor.id
    draft.approved_at = now
    draft.published_on = now.date()
    draft.locked = True
    adj.status = AdjustmentStatus.EFFECTIVE
    adj.result_version_id = draft.id
    adj.effective_at = now
    db.flush()
    _record(db, actor, TYPE_ADJUSTMENT, adj.id, "ceo", "approve")
    audit(db, actor, action="adjustment_effective", object_type="target_adjustment", object_id=adj.id,
          before={"status": AdjustmentStatus.PENDING_CEO},
          after={"status": adj.status, "version": f"V{next_no}", "version_id": draft.id, "approved_at": now,
                 "adjust_reason": reasons})
    notify(db, biz_type="adjustment_effective", biz_id=adj.id, users=users_with_role(db, Role.FINANCE_HEAD),
           title="【已生效】目标调整", name=f"{adj.year} Q{adj.quarter} 目标调整", object_name=f"调整后目标 V{next_no}",
           period=f"{adj.year} Q{adj.quarter}", link=_link("/versions"))
    return {"type": TYPE_ADJUSTMENT, "id": adj.id, "status": adj.status, "version_id": draft.id,
            "version": f"V{next_no}"}


def _reject_adjustment(db, actor: Actor, adj_id: int, reason: str) -> dict:
    if not actor.has_role(Role.CEO):
        raise Forbidden()
    adj = db.scalar(select(TargetAdjustment).where(TargetAdjustment.id == adj_id).with_for_update())
    if adj is None:
        raise NotFound("目标调整不存在")
    if adj.status != AdjustmentStatus.PENDING_CEO:
        raise Conflict(STATE_CHANGED, code="state_changed")
    adj.status = AdjustmentStatus.IN_PROGRESS
    adj.ceo_return_reason = reason
    db.flush()
    _record(db, actor, TYPE_ADJUSTMENT, adj.id, "ceo", "reject", reason)
    audit(db, actor, action="adjustment_returned", object_type="target_adjustment", object_id=adj.id,
          before={"status": AdjustmentStatus.PENDING_CEO}, after={"status": adj.status, "reason": reason})
    notify(db, biz_type="adjustment_returned", biz_id=adj.id, users=users_with_role(db, Role.FINANCE_HEAD),
           title="【已退回】目标调整终审", name=f"{adj.year} Q{adj.quarter} 目标调整", object_name="CEO 整次退回",
           period=f"{adj.year} Q{adj.quarter}", link=_link(f"/approvals/{TYPE_ADJUSTMENT}/{adj.id}"))
    return {"type": TYPE_ADJUSTMENT, "id": adj.id, "status": adj.status}


def my_units(db, user) -> list[dict]:
    """填报人「我的目标调整」：进行中（或最近一次）调整里本人负责的单位。"""
    actor = as_actor(db, user)
    rows = db.scalars(select(FillingUnit).join(TargetAdjustment, TargetAdjustment.id == FillingUnit.adjustment_id)
                      .where(FillingUnit.filler_id == actor.id,
                             TargetAdjustment.status.in_((AdjustmentStatus.IN_PROGRESS,
                                                          AdjustmentStatus.PENDING_CEO)))
                      .order_by(FillingUnit.id)).all()
    return [unit_view(db, u) for u in rows]
