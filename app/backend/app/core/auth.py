"""认证与会话 CMP-F01-02（AC-F01-01~03、DEC-012、DEC-013、DEC-019）。

- 会话：256 位随机令牌，库中只存 SHA-256；Cookie budget_session（HttpOnly、SameSite=Lax）；8 小时无操作失效。
- 每次请求：校验会话 → 用户启用 → 至少一个角色（角色与范围每次重新加载，不缓存）。
- 停用账号：登录被拒；已有会话在下一次请求时返回 401 并删除。
- 生产配置下拒绝 auth_source=dev 的会话（启动时另行清除）。
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.audit import write_audit
from app.core.clock import clock
from app.core.errors import AppError, Unauthenticated
from app.db import get_db
from app.models import User, UserRole, UserSession
from app.models.enums import AuthSource, Role

SESSION_COOKIE = "budget_session"
NO_ROLE_MESSAGE = "未开通预算权限，请联系财务负责人"
ACCOUNT_DISABLED_MESSAGE = "无法登录：钉钉账号已停用或不在企业通讯录中"
# 每次请求都刷新最近活动时间会产生大量写入；间隔小于该值时不刷新（对 8 小时窗口无影响）
_TOUCH_INTERVAL = timedelta(seconds=60)


class NoRole(AppError):
    status_code = 403
    code = "no_role"
    message = NO_ROLE_MESSAGE


class AccountDisabled(AppError):
    """登录时 403；已有会话失效时由调用方改为 401。"""
    status_code = 403
    code = "account_disabled"
    message = ACCOUNT_DISABLED_MESSAGE


@dataclass(frozen=True)
class CurrentUser:
    user: User
    roles: frozenset[str]
    auth_source: str
    session_id: int

    @property
    def role_names(self) -> list[str]:
        return [Role.LABELS[r] for r in Role.ALL if r in self.roles]

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles & set(roles))


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load_roles(db: Session, user_id: int) -> frozenset[str]:
    return frozenset(db.scalars(select(UserRole.role_code).where(UserRole.user_id == user_id)))


def create_session(db: Session, user: User, auth_source: str, settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    now = clock.now()
    db.add(UserSession(token_hash=hash_token(token), user_id=user.id, auth_source=auth_source,
                       last_active_at=now, expires_at=now + timedelta(hours=settings.SESSION_IDLE_HOURS)))
    db.flush()
    return token


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=settings.COOKIE_SECURE,
                        path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def revoke_user_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(UserSession).where(UserSession.user_id == user_id))


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    settings = get_app_settings(request)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthenticated()
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None:
        raise Unauthenticated()
    now = clock.now()
    if session.auth_source == AuthSource.DEV and not settings.dev_identity_enabled:
        db.delete(session)
        db.commit()
        raise Unauthenticated()
    if session.last_active_at + timedelta(hours=settings.SESSION_IDLE_HOURS) <= now:
        db.delete(session)
        db.commit()
        raise Unauthenticated("登录已过期，请重新登录", code="session_expired")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        revoke_user_sessions(db, session.user_id)
        db.commit()
        raise Unauthenticated(ACCOUNT_DISABLED_MESSAGE, code="account_disabled")
    roles = load_roles(db, user.id)
    if not roles:
        raise NoRole()
    if now - session.last_active_at >= _TOUCH_INTERVAL:
        session.last_active_at = now
        session.expires_at = now + timedelta(hours=settings.SESSION_IDLE_HOURS)
        db.commit()
    return CurrentUser(user=user, roles=roles, auth_source=session.auth_source, session_id=session.id)


def login_user(db: Session, user: User, auth_source: str, settings: Settings, request: Request | None) -> str:
    """用户已确认在钉钉通讯录中启用（或开发身份）：校验角色、建会话、写审计。调用方负责 commit。"""
    if not user.is_active:
        write_audit(db, action="login_rejected", object_type="user", object_id=user.id,
                    after={"reason": "account_disabled"}, actor_name=user.name, request=request,
                    auth_source=auth_source)
        raise AccountDisabled()
    roles = load_roles(db, user.id)
    if not roles:
        write_audit(db, action="login_rejected", object_type="user", object_id=user.id,
                    after={"reason": "no_role"}, actor_name=user.name, request=request, auth_source=auth_source)
        raise NoRole()
    token = create_session(db, user, auth_source, settings)
    write_audit(db, action="login", object_type="user", object_id=user.id, after={"roles": sorted(roles)},
                actor_name=user.name, request=request, auth_source=auth_source)
    return token


def sync_user_from_directory(db: Session, userid: str, info) -> User | None:
    """按钉钉通讯录实时信息更新本地用户；info 为空（不在通讯录）或停用时把本地用户标为停用并撤销会话。

    返回本地用户（可能为 None：通讯录中不存在且本地也没有）。
    """
    user = db.scalar(select(User).where(User.dingtalk_userid == userid))
    now = clock.now()
    if info is None or not info.active:
        if user is not None:
            user.is_active = False
            user.synced_at = now
            revoke_user_sessions(db, user.id)
        return user
    if user is None:
        user = User(dingtalk_userid=userid, name=info.name, union_id=info.unionid, dingtalk_dept=info.dept_name,
                    is_active=True, synced_at=now)
        db.add(user)
        db.flush()
    else:
        user.name = info.name or user.name
        user.union_id = info.unionid or user.union_id
        user.dingtalk_dept = info.dept_name or user.dingtalk_dept
        user.is_active = True
        user.synced_at = now
    return user


def safe_return_path(path: str | None) -> str:
    """登录后回到原链接，只接受站内相对路径，防止开放重定向。"""
    if path and path.startswith("/") and not path.startswith("//") and "\\" not in path:
        return path
    return "/"


def purge_dev_sessions(db: Session) -> int:
    """生产配置启动时清除开发身份会话（DEC-013 第 4 条）。"""
    result = db.execute(delete(UserSession).where(UserSession.auth_source == AuthSource.DEV))
    return result.rowcount or 0


def bootstrap_finance_head(db: Session, settings: Settings) -> bool:
    """DEC-019：系统内没有启用的财务负责人时，为 BOOTSTRAP_FINANCE_HEAD_USERID 授予财务负责人（幂等）。"""
    userid = settings.BOOTSTRAP_FINANCE_HEAD_USERID
    if not userid:
        return False
    exists = db.scalar(
        select(User.id).join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_code == Role.FINANCE_HEAD, User.is_active.is_(True)).limit(1))
    if exists:
        return False
    user = db.scalar(select(User).where(User.dingtalk_userid == userid))
    if user is None:
        user = User(dingtalk_userid=userid, name=userid, is_active=True)
        db.add(user)
        db.flush()
    user.is_active = True
    if db.get(UserRole, (user.id, Role.FINANCE_HEAD)) is None:
        db.add(UserRole(user_id=user.id, role_code=Role.FINANCE_HEAD))
    write_audit(db, action="bootstrap_finance_head", object_type="user", object_id=user.id,
                after={"roles": [Role.FINANCE_HEAD]})
    return True


def finance_head_missing(db: Session) -> bool:
    return db.scalar(
        select(User.id).join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_code == Role.FINANCE_HEAD, User.is_active.is_(True)).limit(1)) is None
