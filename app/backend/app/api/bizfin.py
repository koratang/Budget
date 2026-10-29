"""业财分析（API-F15-01~02）。查看：CEO、财务负责人、财务BP；编辑：财务负责人、财务BP。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser
from app.core.scope import require_roles
from app.db import get_db
from app.models.enums import Role
from app.services import bizfin as svc

router = APIRouter(prefix="/bizfin", tags=["bizfin"])

VIEWERS = (Role.CEO, Role.FINANCE_HEAD, Role.FINANCE_BP)
EDITORS = (Role.FINANCE_HEAD, Role.FINANCE_BP)


@router.get("/sections")
def get_sections(current: CurrentUser = Depends(require_roles(*VIEWERS)), db: Session = Depends(get_db)):
    return {"sections": svc.sections(db), "can_edit": current.has_role(*EDITORS)}


@router.put("/sections/{key}")
def save_section(key: str, body: dict, current: CurrentUser = Depends(require_roles(*EDITORS)),
                 db: Session = Depends(get_db)):
    data = svc.save(db, current, key, body)
    db.commit()
    return data
