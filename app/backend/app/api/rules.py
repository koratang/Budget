"""规则库（API-F12-01/02）。查看：财务BP、财务负责人、CEO；新建与提交新版本：财务BP、财务负责人。
审批由 /approvals（G2）按 type = rule-version 分发到 services.rules。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser
from app.core.scope import require_roles
from app.db import get_db
from app.models.enums import Role
from app.services import rules as svc

router = APIRouter(prefix="/rules", tags=["rules"])

VIEWERS = (Role.FINANCE_BP, Role.FINANCE_HEAD, Role.CEO)
EDITORS = (Role.FINANCE_BP, Role.FINANCE_HEAD)


@router.get("")
def list_rules(type: str | None = None, credibility: str | None = None, state: str | None = None,
               current: CurrentUser = Depends(require_roles(*VIEWERS)), db: Session = Depends(get_db)):
    return {"items": svc.list_rules(db, rule_type=type, credibility=credibility, state=state),
            "can_create": current.has_role(*EDITORS)}


@router.get("/options", dependencies=[Depends(require_roles(*VIEWERS))])
def options(db: Session = Depends(get_db)):
    return svc.options(db)


@router.post("")
def create_rule(body: dict, current: CurrentUser = Depends(require_roles(*EDITORS)), db: Session = Depends(get_db)):
    rule = svc.create_rule(db, current, body)
    data = svc.rule_detail(db, svc.as_actor(db, current), rule.id)
    db.commit()
    return data


@router.get("/{rule_id}")
def rule_detail(rule_id: int, current: CurrentUser = Depends(require_roles(*VIEWERS)),
                db: Session = Depends(get_db)):
    return svc.rule_detail(db, svc.as_actor(db, current), rule_id)


@router.post("/{rule_id}/versions")
def submit_version(rule_id: int, body: dict, current: CurrentUser = Depends(require_roles(*EDITORS)),
                   db: Session = Depends(get_db)):
    svc.submit_version(db, current, rule_id, body)
    data = svc.rule_detail(db, svc.as_actor(db, current), rule_id)
    db.commit()
    return data
