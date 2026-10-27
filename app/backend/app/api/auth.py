"""认证接口（API-F01-01~04、API-F01-06；SEQ-F01-01）。

- GET  /auth/config               登录页配置（生产恒不显示开发身份切换）
- GET  /auth/dingtalk/qr-url      扫码授权地址（redirect = 登录后回到的站内路径）
- GET  /auth/dingtalk/callback    扫码回调：默认 302 跳转（成功回原链接，失败回 /login?error=code）；format=json 返回 JSON
- POST /auth/dingtalk/h5          工作台免登
- POST /auth/logout               注销
- GET  /auth/dev-users、POST /dev/login-as（别名 POST /auth/dev-login）
                                  仅 APP_ENV=dev 且 DEV_IDENTITY_SWITCH=true 时注册（DEC-013）
被拒错误码：no_role（details.name =「姓名（部门）」）、account_disabled、dingtalk_auth_failed、dingtalk_unavailable。
"""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.audit import write_audit
from app.core.auth import (AccountDisabled, CurrentUser, NoRole, SESSION_COOKIE, clear_session_cookie,
                           get_app_settings, get_current_user, hash_token, load_roles, login_user,
                           safe_return_path, set_session_cookie, sync_user_from_directory)
from app.core.errors import AppError, NotFound
from app.db import get_db
from app.dingtalk import get_dingtalk
from app.dingtalk.gateway import DingTalkAuthError, DingTalkClient, DingTalkError
from app.models import Department, User, UserRole, UserSession
from app.models.enums import AuthSource, Role

router = APIRouter(prefix="/auth", tags=["auth"])
dev_router = APIRouter(tags=["auth-dev"])


class DingTalkAuthFailed(AppError):
    status_code = 401
    code = "dingtalk_auth_failed"
    message = "钉钉身份验证失败，请重新登录"


class DingTalkUnavailable(AppError):
    status_code = 503
    code = "dingtalk_unavailable"
    message = "钉钉登录暂不可用，请稍后重试"


def _user_payload(db: Session, user: User) -> dict:
    roles = load_roles(db, user.id)
    return {"user": {"id": user.id, "name": user.name, "dingtalk_userid": user.dingtalk_userid},
            "roles": [r for r in Role.ALL if r in roles],
            "role_names": [Role.LABELS[r] for r in Role.ALL if r in roles]}


def _dingtalk_login(db: Session, client: DingTalkClient, userid: str, settings: Settings,
                    request: Request) -> tuple[User, str]:
    """钉钉身份已验证：实时校验通讯录状态 → 角色 → 建会话。拒绝时先提交审计再抛错。"""
    try:
        info = client.get_user(userid)
    except DingTalkError as e:
        raise DingTalkUnavailable() from e
    user = sync_user_from_directory(db, userid, info)
    try:
        if user is None or not user.is_active:
            write_audit(db, action="login_rejected", object_type="user",
                        object_id=user.id if user else None, after={"reason": "account_disabled", "userid": userid},
                        actor_name=user.name if user else userid, request=request,
                        auth_source=AuthSource.DINGTALK)
            raise AccountDisabled()
        token = login_user(db, user, AuthSource.DINGTALK, settings, request)
    except AppError:
        db.commit()
        raise
    db.commit()
    return user, token


@router.get("/config")
def auth_config(settings: Settings = Depends(get_app_settings)):
    return {"corp_id": settings.DINGTALK_CORP_ID, "client_id": settings.DINGTALK_APP_KEY,
            "dev_switch": settings.dev_identity_enabled}


@router.get("/dingtalk/qr-url")
def qr_url(redirect: str | None = None, settings: Settings = Depends(get_app_settings),
           client: DingTalkClient = Depends(get_dingtalk)):
    callback = f"{settings.APP_BASE_URL.rstrip('/')}/api/auth/dingtalk/callback"
    return {"url": client.qr_login_url(callback, safe_return_path(redirect))}


@router.get("/dingtalk/callback")
def dingtalk_callback(request: Request, code: str | None = None,
                      auth_code: str | None = Query(None, alias="authCode"), state: str | None = None,
                      format: str | None = None, db: Session = Depends(get_db),
                      settings: Settings = Depends(get_app_settings),
                      client: DingTalkClient = Depends(get_dingtalk)):
    target = safe_return_path(state)
    want_json = format == "json"
    try:
        the_code = code or auth_code
        if not the_code:
            raise DingTalkAuthFailed()
        try:
            userid = client.userid_from_qr_code(the_code)
        except DingTalkAuthError as e:
            raise DingTalkAuthFailed() from e
        except DingTalkError as e:
            raise DingTalkUnavailable() from e
        user, token = _dingtalk_login(db, client, userid, settings, request)
    except AppError as e:
        if want_json:
            raise
        params = {"error": e.code}
        if e.details.get("name"):
            params["name"] = e.details["name"]
        if target != "/":
            params["redirect"] = target
        return RedirectResponse("/login?" + urlencode(params), status_code=302)
    if want_json:
        response: Response = JSONResponse({**_user_payload(db, user), "redirect": target})
    else:
        response = RedirectResponse(target, status_code=302)
    set_session_cookie(response, token, settings)
    return response


class H5LoginIn(BaseModel):
    auth_code: str
    redirect: str | None = None


@router.post("/dingtalk/h5")
def dingtalk_h5(body: H5LoginIn, request: Request, response: Response, db: Session = Depends(get_db),
                settings: Settings = Depends(get_app_settings), client: DingTalkClient = Depends(get_dingtalk)):
    try:
        userid = client.userid_from_h5_code(body.auth_code)
    except DingTalkAuthError as e:
        raise DingTalkAuthFailed() from e
    except DingTalkError as e:
        raise DingTalkUnavailable() from e
    user, token = _dingtalk_login(db, client, userid, settings, request)
    set_session_cookie(response, token, settings)
    return {**_user_payload(db, user), "redirect": safe_return_path(body.redirect)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
        if session is not None:
            db.delete(session)
            db.commit()
    clear_session_cookie(response)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 开发身份模拟（DEC-002 / DEC-013）：仅开发配置注册
# ---------------------------------------------------------------------------
@dev_router.get("/auth/dev-users")
def dev_users(db: Session = Depends(get_db)):
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id)).all()
    roles_by_user: dict[int, set[str]] = {}
    for uid, code in db.execute(select(UserRole.user_id, UserRole.role_code)):
        roles_by_user.setdefault(uid, set()).add(code)
    depts = dict(db.execute(select(Department.id, Department.name)).all())
    result = []
    for u in users:
        roles = [r for r in Role.ALL if r in roles_by_user.get(u.id, set())]
        role_names = [Role.LABELS[r] for r in roles]
        dept = depts.get(u.department_id) or u.dingtalk_dept
        label = f"{u.name} · {'、'.join(role_names)}" if roles else f"{u.name} · 未分配角色"
        result.append({"id": u.id, "name": u.name, "dingtalk_userid": u.dingtalk_userid, "department": dept,
                       "roles": roles, "role_names": role_names, "label": f"{label}（{dept}）" if dept else label})
    return result


class DevLoginIn(BaseModel):
    user_id: int


@dev_router.post("/dev/login-as")
@dev_router.post("/auth/dev-login")
def dev_login(body: DevLoginIn, request: Request, response: Response, db: Session = Depends(get_db),
              settings: Settings = Depends(get_app_settings)):
    user = db.get(User, body.user_id)
    if user is None:
        raise NotFound("用户不存在")
    try:
        token = login_user(db, user, AuthSource.DEV, settings, request)
    except (NoRole, AccountDisabled):
        db.commit()
        raise
    db.commit()
    set_session_cookie(response, token, settings)
    return _user_payload(db, user)


@router.get("/session")
def current_session(current: CurrentUser = Depends(get_current_user)):
    """会话探测：前端判断是否已登录（未登录 401）。"""
    return {"user_id": current.user.id, "auth_source": current.auth_source}
