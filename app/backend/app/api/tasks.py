"""编制任务（API-F03-01~03）。

- GET  /tasks                                  任务列表（财务负责人；CEO 只读）
- GET  /tasks/candidates                       发布弹窗：可参与的填报单位及填报人（财务负责人）
- POST /tasks                                  发布（同年度唯一；按 AC-F03-05 生成单位；通知填报人）
- GET  /tasks/{id}/progress                    进度看板（提交率、逾期、CEO 退回原因）
- POST /tasks/{id}/submit-to-ceo               提交 CEO（未全部通过时 422 并列出单位）
- POST /tasks/{id}/units/{unit_id}/return      CEO 退回后把指定单位退回填报人（原因必填）
"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.auth import CurrentUser, get_app_settings
from app.core.scope import ScopeContext, get_scope, require_roles
from app.db import get_db
from app.models.enums import Role
from app.services import tasking

router = APIRouter(prefix="/tasks", tags=["tasks"])


class UnitRef(BaseModel):
    unit_type: str
    scope_object_id: int | None = None


class PublishIn(BaseModel):
    year: int | None = None
    deadline: date | None = None
    units: list[UnitRef] | None = None


class ReasonIn(BaseModel):
    reason: str | None = None


@router.get("")
def list_tasks(ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    tasking.ensure_task_reader(ctx)
    return {"items": tasking.list_tasks(db), "can_publish": ctx.has_role(Role.FINANCE_HEAD)}


@router.get("/candidates")
def candidates(_: CurrentUser = Depends(require_roles(Role.FINANCE_HEAD)), db: Session = Depends(get_db)):
    return {"items": [c.to_dict() for c in tasking.unit_candidates(db)]}


@router.post("", status_code=201)
def publish(body: PublishIn, request: Request, current: CurrentUser = Depends(require_roles(Role.FINANCE_HEAD)),
            settings: Settings = Depends(get_app_settings), db: Session = Depends(get_db)):
    result = tasking.publish_task(db, current, settings, year=body.year, deadline=body.deadline,
                                  units=[u.model_dump() for u in body.units] if body.units is not None else None,
                                  request=request)
    db.commit()
    return result


@router.get("/{task_id}/progress")
def progress(task_id: int, ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    tasking.ensure_task_reader(ctx)
    return tasking.task_progress(db, ctx, task_id)


@router.post("/{task_id}/submit-to-ceo")
def submit_to_ceo(task_id: int, request: Request, current: CurrentUser = Depends(require_roles(Role.FINANCE_HEAD)),
                  settings: Settings = Depends(get_app_settings), db: Session = Depends(get_db)):
    result = tasking.submit_to_ceo(db, current, settings, task_id, request=request)
    db.commit()
    return result


@router.post("/{task_id}/units/{unit_id}/return")
def return_unit(task_id: int, unit_id: int, body: ReasonIn, request: Request,
                current: CurrentUser = Depends(require_roles(Role.FINANCE_HEAD)),
                settings: Settings = Depends(get_app_settings), db: Session = Depends(get_db)):
    result = tasking.return_unit_to_filler(db, current, settings, task_id, unit_id, body.reason, request=request)
    db.commit()
    return result
