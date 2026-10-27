"""偏差报告（API-F10-01~05）：/reports、/variance-notes。

每个路由声明 Depends(get_scope) 或 require_roles(...)；查询经 ScopeContext 过滤（NFR-003），
越权返回 403「无权限」且不含记录字段（AC-F01-11）。
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import CurrentUser
from app.core.scope import ScopeContext, get_scope, require_roles
from app.db import get_db
from app.models.enums import Role
from app.services import reports as svc

router = APIRouter(prefix="", tags=["reports"])


@router.get("/reports/company")
def company(year: int | None = None, ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    return svc.company_summary(db, ctx, year)


@router.get("/reports/channel-site")
def channel_site(month: str | None = None, baseline: str = "adj", channel: str | None = None,
                 ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    return svc.channel_site(db, ctx, month, baseline, channel)


@router.get("/reports/category")
def category(month: str | None = None, ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    return svc.category_report(db, ctx, month)


@router.get("/reports/dept-expense")
def dept_expense(year: int | None = None, department_id: int | None = None, ctx: ScopeContext = Depends(get_scope),
                 db: Session = Depends(get_db)):
    return svc.dept_report(db, ctx, year, department_id)


class NoteIn(BaseModel):
    report_type: str
    month: str
    object_type: str
    object_key: str
    note: str = ""


@router.put("/variance-notes")
def save_note(body: NoteIn, request: Request, current: CurrentUser = Depends(require_roles(Role.FINANCE_BP)),
              db: Session = Depends(get_db)):
    """偏差说明（AC-F10-11）：只有财务BP 可填写；只保留最新一条，修改前后值进入审计日志。"""
    row, before = svc.save_note(db, current.user, report_type=body.report_type, month=body.month,
                                object_type=body.object_type, object_key=body.object_key, note=body.note)
    write_audit(db, action="variance_note.save", object_type="variance_note", object_id=row.id, before=before,
                after={"report_type": row.report_type, "month": row.month, "object_type": row.object_type,
                       "object_key": row.object_key, "note": row.note}, actor=current, request=request)
    result = {"id": row.id, "report_type": row.report_type, "month": body.month, "object_type": row.object_type,
              "object_key": row.object_key, **svc.note_dict(row, current.user.name)}
    db.commit()
    return result
