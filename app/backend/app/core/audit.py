"""审计记录器 CMP-F00-02：在业务事务内写只追加审计行（NFR-004、DEC-010）。

调用方在同一 Session 内先改业务数据、再调用 write_audit，最后统一 commit——业务成功则审计必在。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.clock import clock
from app.models import AuditLog

if TYPE_CHECKING:
    from app.core.auth import CurrentUser

SYSTEM_ACTOR = "system-bootstrap"


def to_jsonable(value: Any) -> Any:
    """Decimal → 字符串、日期 → ISO，递归处理容器。"""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    return value


def write_audit(
    db: Session,
    *,
    action: str,
    object_type: str,
    object_id: Any = None,
    before: Any = None,
    after: Any = None,
    actor: CurrentUser | None = None,
    actor_name: str | None = None,
    request: Request | None = None,
    auth_source: str | None = None,
) -> AuditLog:
    """写入一条审计行（不提交）。actor 为空时 actor_name 必填（如 system-bootstrap、登录被拒的钉钉用户）。"""
    user = actor.user if actor else None
    row = AuditLog(
        occurred_at=clock.now(),  # 业务时间统一取可注入时钟（生产即当前时间）
        actor_id=user.id if user else None,
        actor_userid=user.dingtalk_userid if user else None,
        actor_name=user.name if user else (actor_name or SYSTEM_ACTOR),
        action=action,
        object_type=object_type,
        object_id=None if object_id is None else str(object_id),
        before=to_jsonable(before),
        after=to_jsonable(after),
        request_id=getattr(request.state, "request_id", None) if request else None,
        ip=request.client.host if request and request.client else None,
        auth_source=auth_source or (actor.auth_source if actor else None),
    )
    db.add(row)
    db.flush()
    return row
