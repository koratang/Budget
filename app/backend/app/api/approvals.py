"""审批（API-F07-01/02）：统一对外，按类型分发到服务模块（第二期分工「跨组接口」）。

- GET  /approvals?tab=pending|done                 待处理（各模块 pending_items 汇总）/ 已处理（审批记录）
- GET  /approvals/{type}/{id}                      审批详情（只读）
- POST /approvals/{type}/{id}/approve              通过
- POST /approvals/{type}/{id}/reject {reason}      退回（原因为空 422「请填写退回原因」）
type：unit / task（G2 approval_units）、adjustment-unit / adjustment（G3 adjustments）、rule-version（G3 rules）。
模块用 importlib 安全导入，缺失时该类型待办为空、详情 404。模块函数接受 obj_type 关键字参数时传入类型。
"""
import importlib
import inspect
from types import ModuleType

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser
from app.core.errors import NotFound, ValidationFailed
from app.core.scope import require_roles
from app.db import get_db
from app.models import ApprovalRecord, BudgetTask, FillingUnit, Rule, RuleVersion, TargetAdjustment, User
from app.models.enums import Role

router = APIRouter(prefix="/approvals", tags=["approvals"])

APPROVERS = (Role.DEPT_HEAD, Role.FINANCE_HEAD, Role.CEO)
TYPE_MODULES = {
    "unit": "app.services.approval_units",
    "task": "app.services.approval_units",
    "adjustment-unit": "app.services.adjustments",
    "adjustment": "app.services.adjustments",
    "rule-version": "app.services.rules",
}
KIND_LABELS = {"unit": "预算编制", "task": "预算编制", "adjustment-unit": "目标调整", "adjustment": "目标调整",
               "rule-version": "规则审批"}
REASON_REQUIRED = "请填写退回原因"


class RejectIn(BaseModel):
    reason: str | None = None


def _module(name: str) -> ModuleType | None:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _call(fn, *args, obj_type: str):
    """模块函数声明了 obj_type 参数时传入类型（一个模块服务多种类型），否则按固定签名调用。"""
    if "obj_type" in inspect.signature(fn).parameters:
        return fn(*args, obj_type=obj_type)
    return fn(*args)


def _handler(obj_type: str, fn_name: str):
    name = TYPE_MODULES.get(obj_type)
    module = _module(name) if name else None
    fn = getattr(module, fn_name, None) if module else None
    if fn is None:
        raise NotFound("该审批事项已不存在或已被处理")
    return fn


def _title(db: Session, obj_type: str, obj_id: int) -> str:
    """已处理列表的事项名称（直接读模型表）。"""
    if obj_type in ("unit", "adjustment-unit"):
        unit = db.get(FillingUnit, obj_id)
        if unit is None:
            return f"#{obj_id}"
        if unit.task_id:
            task = db.get(BudgetTask, unit.task_id)
            return f"{task.year} 年度预算 · {unit.name}"
        adj = db.get(TargetAdjustment, unit.adjustment_id)
        return f"{adj.year} Q{adj.quarter} 目标调整 · {unit.name}"
    if obj_type == "task":
        task = db.get(BudgetTask, obj_id)
        return f"{task.name} · 全公司预算" if task else f"#{obj_id}"
    if obj_type == "adjustment":
        adj = db.get(TargetAdjustment, obj_id)
        return f"{adj.year} Q{adj.quarter} 目标调整（整次终审）" if adj else f"#{obj_id}"
    if obj_type == "rule-version":
        rv = db.get(RuleVersion, obj_id)
        rule = db.get(Rule, rv.rule_id) if rv else None
        return f"{rule.name}（v{rv.version_no}）" if rule else f"#{obj_id}"
    return f"#{obj_id}"


def _pending(db: Session, current: CurrentUser) -> list[dict]:
    items: list[dict] = []
    for name in dict.fromkeys(TYPE_MODULES.values()):
        module = _module(name)
        fn = getattr(module, "pending_items", None) if module else None
        if fn is None:
            continue
        for it in fn(db, current):
            it.setdefault("kind_label", KIND_LABELS.get(it.get("type"), ""))
            items.append(it)
    items.sort(key=lambda it: it.get("submitted_at") or "", reverse=True)
    return items


def _done(db: Session, current: CurrentUser) -> list[dict]:
    rows = db.scalars(select(ApprovalRecord).where(ApprovalRecord.approver_id == current.user.id)
                      .order_by(ApprovalRecord.created_at.desc(), ApprovalRecord.id.desc()))
    out = []
    for r in rows:
        out.append({"type": r.object_type, "id": r.object_id, "title": _title(db, r.object_type, r.object_id),
                    "kind_label": KIND_LABELS.get(r.object_type, ""), "action": r.action,
                    "result": "已通过" if r.action == "approve" else "已退回", "reason": r.reason,
                    "handled_at": r.created_at.isoformat(), "link": f"/approvals/{r.object_type}/{r.object_id}"})
    return out


@router.get("")
def list_approvals(tab: str = "pending", current: CurrentUser = Depends(require_roles(*APPROVERS)),
                   db: Session = Depends(get_db)):
    pending = _pending(db, current)
    done = _done(db, current)
    for it in pending:
        if it.get("submitter") is None and it.get("type") in ("unit", "adjustment-unit"):
            unit = db.get(FillingUnit, it["id"])
            it["submitter"] = db.scalar(select(User.name).where(User.id == unit.filler_id)) if unit else None
    return {"tab": tab, "items": pending if tab == "pending" else done,
            "pending_count": len(pending), "done_count": len(done)}


@router.get("/{obj_type}/{obj_id}")
def detail(obj_type: str, obj_id: int, current: CurrentUser = Depends(require_roles(*APPROVERS)),
           db: Session = Depends(get_db)):
    return _call(_handler(obj_type, "detail"), db, current, obj_id, obj_type=obj_type)


@router.post("/{obj_type}/{obj_id}/approve")
def approve(obj_type: str, obj_id: int, current: CurrentUser = Depends(require_roles(*APPROVERS)),
            db: Session = Depends(get_db)):
    result = _call(_handler(obj_type, "approve"), db, current, obj_id, obj_type=obj_type)
    db.commit()
    return result


@router.post("/{obj_type}/{obj_id}/reject")
def reject(obj_type: str, obj_id: int, body: RejectIn, current: CurrentUser = Depends(require_roles(*APPROVERS)),
           db: Session = Depends(get_db)):
    fn = _handler(obj_type, "reject")
    if not (body.reason or "").strip():
        raise ValidationFailed(REASON_REQUIRED, code="reason_required")
    result = _call(fn, db, current, obj_id, body.reason.strip(), obj_type=obj_type)
    db.commit()
    return result
