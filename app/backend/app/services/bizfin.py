"""业财分析工作区存取（CMP-F15-01）：按部分读写 JSON 文档，revision 乐观锁，每次保存写审计。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import write_audit
from app.core.auth import CurrentUser
from app.core.clock import clock
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models import BizfinSection
from app.models.bizfin import SECTION_KEYS

LABELS = {"indicators": "财务与业务指标", "biz_dim": "业务指标维度填报", "policy": "政策环境事件", "keywork": "重点工作"}


def _view(row: BizfinSection) -> dict:
    return {"data": row.data, "is_demo": row.is_demo, "revision": row.revision, "updated_by": row.updated_by,
            "updated_at": row.updated_at.isoformat()}


def sections(db: Session) -> dict:
    """已保存的部分；未保存过的部分不返回，前端用示例数据（is_demo）。"""
    rows = db.scalars(select(BizfinSection)).all()
    return {r.key: _view(r) for r in rows}


def save(db: Session, current: CurrentUser, key: str, body: dict) -> dict:
    if key not in SECTION_KEYS:
        raise NotFound()
    data, revision, is_demo = body.get("data"), body.get("revision"), body.get("is_demo")
    if not isinstance(data, (dict, list)) or not isinstance(is_demo, bool) or not (
            revision is None or isinstance(revision, int)):
        raise ValidationFailed()
    row = db.get(BizfinSection, key, with_for_update=True)
    current_rev = row.revision if row else None
    if revision != current_rev:
        raise Conflict(f"「{LABELS[key]}」已被{row.updated_by if row else '他人'}更新，请刷新后再改",
                       details={"revision": current_rev})
    if row is None:
        row = BizfinSection(key=key, revision=0)
        db.add(row)
    row.data, row.is_demo, row.revision = data, is_demo, row.revision + 1
    row.updated_by, row.updated_at = current.user.name, clock.now()
    db.flush()
    # 文档可能较大，审计只记部分、版本号与示例标记，内容由版本号对应的保存动作追溯
    write_audit(db, action="bizfin.save", object_type="bizfin_section", object_id=key, actor=current,
                before={"revision": current_rev}, after={"revision": row.revision, "is_demo": is_demo})
    return _view(row)


def reset(db: Session, current: CurrentUser) -> None:
    """恢复示例数据：清空全部已保存部分。"""
    rows = db.scalars(select(BizfinSection)).all()
    for r in rows:
        db.delete(r)
    write_audit(db, action="bizfin.reset", object_type="bizfin_section", actor=current,
                before={"keys": sorted(r.key for r in rows)}, after=None)
