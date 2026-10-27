"""部门费用与专项预留额度（API-F05-01/02）：/dept-expense、/reserves。

- GET  /dept-expense/my-unit                 部门费用入口：本人的部门费用单位
- GET  /dept-expense/{unit_id}/grid          科目 × 月表格 + 历史参考（保存复用 PATCH /filling-units/{id}/cells）
- GET  /reserves?department_id=              专项列表（含上年同科目实际、已用、剩余、使用明细）
- POST /reserves                             新增专项（部门预算专员）
- POST /reserves/{id}/usages                 登记使用（财务BP）
"""
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, get_current_user
from app.core.errors import NotFound, ValidationFailed
from app.core.scope import ScopeContext, get_scope, require_roles
from app.db import get_db
from app.models.enums import Role, UnitType
from app.services import dept_expense, filling, tasking

router = APIRouter(prefix="", tags=["dept_expense"])


class ReserveIn(BaseModel):
    department_id: int | None = None
    name: str | None = None
    account_id: int | None = None
    plan_month: str | None = None
    amount: Any = None


class UsageIn(BaseModel):
    amount: Any = None
    used_on: str | None = None
    voucher_no: str | None = None


@router.get("/dept-expense/my-unit")
def my_unit(ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    found = dept_expense.my_dept_unit(db, ctx)
    if found is None:
        raise NotFound("你目前没有部门费用填报单位")
    return found


@router.get("/dept-expense/{unit_id}/grid")
def grid(unit_id: int, ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    unit = tasking.get_unit(db, unit_id)
    if unit.unit_type != UnitType.DEPT_EXPENSE:
        raise ValidationFailed("该填报单位不是部门费用", code="not_dept_expense")
    return filling.build_grid(db, ctx, unit)


@router.get("/reserves")
def list_reserves(department_id: int | None = None, ctx: ScopeContext = Depends(get_scope),
                  db: Session = Depends(get_db)):
    return dept_expense.list_reserves(db, ctx, department_id)


@router.post("/reserves", status_code=201)
def create_reserve(body: ReserveIn, request: Request, current: CurrentUser = Depends(get_current_user),
                   ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
    result = dept_expense.create_reserve(db, ctx, current, body.model_dump(), request=request)
    db.commit()
    return result


@router.post("/reserves/{reserve_id}/usages", status_code=201)
def add_usage(reserve_id: int, body: UsageIn, request: Request,
              current: CurrentUser = Depends(require_roles(Role.FINANCE_BP)), ctx: ScopeContext = Depends(get_scope),
              db: Session = Depends(get_db)):
    result = dept_expense.add_usage(db, ctx, current, reserve_id, body.model_dump(), request=request)
    db.commit()
    return result
