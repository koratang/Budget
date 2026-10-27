"""角色与权限（API-F01-07）：员工列表、保存角色与数据范围。

仅财务负责人（AC-F01-05）；其他角色 403「无权限」且不返回任何员工字段（AC-F01-11）。
保存写审计（操作人、时间、前后值，NFR-004）；会使启用的财务负责人为 0 时 409 last_finance_head（DEC-019）。
"""
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import CurrentUser
from app.core.errors import NotFound
from app.core.scope import require_roles
from app.db import get_db
from app.models import User
from app.models.enums import Role
from app.services import roles as svc

router = APIRouter(prefix="/admin", tags=["roles"])
finance_head_only = require_roles(Role.FINANCE_HEAD)


@router.get("/users")
def list_users(q: str | None = None, dept: str | None = None, role: str | None = None, unassigned: bool = False,
               page: int = Query(1, ge=1), current: CurrentUser = Depends(finance_head_only),
               db: Session = Depends(get_db)):
    return svc.list_users(db, q=q, dept=dept, role=role, unassigned=unassigned, page=page)


@router.get("/scope-options")
def scope_options(current: CurrentUser = Depends(finance_head_only), db: Session = Depends(get_db)):
    return svc.scope_options(db)


class RolesIn(BaseModel):
    roles: list[str] = Field(default_factory=list)
    departments: list[int] = Field(default_factory=list)
    channels: list[int] = Field(default_factory=list)
    stores: list[int] = Field(default_factory=list)
    customers: list[int] = Field(default_factory=list)


@router.put("/users/{user_id}/roles")
def save_roles(user_id: int, body: RolesIn, request: Request, current: CurrentUser = Depends(finance_head_only),
               db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("员工不存在")
    before, after = svc.save_user_roles(db, user, body.roles, body.departments, body.channels, body.stores,
                                        body.customers)
    write_audit(db, action="revoke_roles" if not after["roles"] else "assign_roles", object_type="user_role",
                object_id=user.id, before=before, after=after, actor=current, request=request)
    db.commit()
    scopes = after["scopes"]
    return svc.user_payload(user, set(after["roles"]), scopes)
