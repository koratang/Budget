"""工作台（API-F00-01）：按角色的待办与关键数（DEC-001）；待办与预警按服务端数据范围过滤（NFR-003）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, get_current_user
from app.core.scope import ScopeContext, get_scope
from app.db import get_db
from app.services import workbench as svc

router = APIRouter(prefix="/workbench", tags=["workbench"])


@router.get("")
def workbench(current: CurrentUser = Depends(get_current_user), ctx: ScopeContext = Depends(get_scope),
              db: Session = Depends(get_db)):
    return svc.workbench(db, current, ctx)
