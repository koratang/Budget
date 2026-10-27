"""认证与会话：AC-F01-01~03（三种登录结果、停用失效）、DEC-013（开发开关生产不可用）、NFR-004 登录审计。"""
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.config import ConfigError, load_settings
from app.core.auth import SESSION_COOKIE, create_session
from app.core.clock import clock
from app.dingtalk.scheduler import run_contact_sync
from app.models import AuditLog, User, UserSession
from app.models.enums import AuthSource
from tests.conftest import DINGTALK_CREDS, TEST_DATABASE_URL, build_client, make_settings

NO_ROLE = "未开通预算权限，请联系财务负责人"
DISABLED = "无法登录：钉钉账号已停用或不在企业通讯录中"


def user_id(db, userid: str) -> int:
    return db.scalar(select(User.id).where(User.dingtalk_userid == userid))


def qr_login(client, userid: str, state: str | None = None):
    params = {"authCode": f"qr-{userid}"}
    if state:
        params["state"] = state
    return client.get("/api/auth/dingtalk/callback", params=params, follow_redirects=False)


# ---- ① 已分配角色：扫码与免登都进入首页，显示姓名与角色 ----
def test_qr_login_with_role_enters_and_returns_to_original_link(seeded, client):
    r = qr_login(client, "wanghao", state="/reports/channel-site?month=2027-04")
    assert r.status_code == 302
    assert r.headers["location"] == "/reports/channel-site?month=2027-04"
    set_cookie = r.headers["set-cookie"]
    assert set_cookie.startswith(f"{SESSION_COOKIE}=") and "HttpOnly" in set_cookie

    me = client.get("/api/me").json()
    assert me["user"]["name"] == "王浩"
    assert me["roles"] == ["operations"] and me["role_names"] == ["运营"]
    assert "my-filling" in me["menus"] and "roles" not in me["menus"] and "report-company" not in me["menus"]
    assert me["all_company"] is False
    assert len(me["scopes"]["stores"]) == 1


def test_qr_callback_rejects_open_redirect(seeded, client):
    r = qr_login(client, "wanghao", state="//evil.example.com/x")
    assert r.headers["location"] == "/"


def test_h5_login_with_role(seeded, client):
    r = client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-linxiao"})
    assert r.status_code == 200
    assert r.json()["user"]["name"] == "林晓" and r.json()["role_names"] == ["财务负责人"]
    me = client.get("/api/me").json()
    assert me["all_company"] is True and "roles" in me["menus"]


# ---- ② 未分配角色：拒绝且不建会话 ----
def test_no_role_rejected_without_session(seeded, client, db):
    r = qr_login(client, "zhaoyiming")
    assert r.status_code == 302
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert urlsplit(r.headers["location"]).path == "/login"
    assert q["error"] == ["no_role"] and q["name"] == ["赵一鸣（视觉部）"]
    assert "set-cookie" not in r.headers

    r = client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-zhaoyiming"})
    assert r.status_code == 403
    assert r.json()["code"] == "no_role" and r.json()["message"] == NO_ROLE
    assert db.scalar(select(UserSession).where(UserSession.user_id == user_id(db, "zhaoyiming"))) is None
    assert client.get("/api/me").status_code == 401


def test_unknown_directory_user_is_created_without_role(seeded, client, stub, db):
    stub.post("/_stub/users", json={"userid": "chenmo", "name": "陈默", "dept_name": "市场部"})
    r = client.get("/api/auth/dingtalk/callback", params={"authCode": "qr-chenmo", "format": "json"})
    assert r.status_code == 403 and r.json()["code"] == "no_role"
    assert db.scalar(select(User).where(User.dingtalk_userid == "chenmo")).name == "陈默"


# ---- ③ 停用：已有会话下一次请求失效，再次登录被拒 ----
def test_disabled_account_session_invalid_and_login_rejected(seeded, client, stub, dingtalk, db):
    assert qr_login(client, "wanghao").status_code == 302
    assert client.get("/api/me").status_code == 200

    stub.patch("/_stub/users/wanghao", json={"active": False})
    stats = run_contact_sync(db, dingtalk)
    assert stats["disabled"] == 1

    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json() == {"code": "account_disabled", "message": DISABLED, "details": {}}

    r = qr_login(client, "wanghao")
    assert parse_qs(urlsplit(r.headers["location"]).query)["error"] == ["account_disabled"]
    r = client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-wanghao"})
    assert r.status_code == 403 and r.json()["message"] == DISABLED


def test_removed_from_directory_is_disabled_by_sync(seeded, client, stub, dingtalk, db):
    client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-zhaolei"})
    assert client.get("/api/me").status_code == 200
    stub.delete("/_stub/users/zhaolei")
    run_contact_sync(db, dingtalk)
    assert db.scalar(select(User.is_active).where(User.dingtalk_userid == "zhaolei")) is False
    assert client.get("/api/me").json()["code"] == "account_disabled"


def test_login_checks_directory_in_real_time(seeded, client, stub, db):
    """停用后尚未同步时，登录时的实时校验也会拒绝并把本地用户标为停用。"""
    stub.patch("/_stub/users/wujing", json={"active": False})
    r = client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-wujing"})
    assert r.status_code == 403 and r.json()["code"] == "account_disabled"
    assert db.scalar(select(User.is_active).where(User.dingtalk_userid == "wujing")) is False


def test_invalid_auth_code(seeded, client):
    r = client.post("/api/auth/dingtalk/h5", json={"auth_code": "bad-code"})
    assert r.status_code == 401 and r.json()["code"] == "dingtalk_auth_failed"


# ---- 会话：8 小时无操作失效、注销、角色撤销 ----
def test_session_expires_after_8_idle_hours(seeded, client, db):
    client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-wanghao"})
    session = db.scalar(select(UserSession).where(UserSession.user_id == user_id(db, "wanghao")))
    clock.set_now(session.last_active_at + timedelta(hours=7, minutes=59))
    assert client.get("/api/me").status_code == 200  # 有操作 → 刷新最近活动时间
    clock.set_now(clock.now() + timedelta(hours=8))
    r = client.get("/api/me")
    assert r.status_code == 401 and r.json()["code"] == "session_expired"


def test_logout(seeded, client):
    client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-wanghao"})
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_roles_reloaded_every_request(seeded, client, db):
    from app.models import UserRole
    client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-wanghao"})
    db.query(UserRole).filter(UserRole.user_id == user_id(db, "wanghao")).delete()
    db.flush()
    r = client.get("/api/me")
    assert r.status_code == 403 and r.json()["code"] == "no_role"


def test_login_writes_audit(seeded, client, db):
    client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-wanghao"})
    client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-zhaoyiming"})
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    assert [(r.action, r.actor_name, r.auth_source) for r in rows][-2:] == [
        ("login", "王浩", "dingtalk"), ("login_rejected", "赵一鸣", "dingtalk")]


# ---- 开发身份（DEC-002 / DEC-013） ----
def test_dev_identity_endpoints_in_dev(seeded, client, db):
    users = client.get("/api/auth/dev-users").json()
    wanghao = next(u for u in users if u["name"] == "王浩")
    assert wanghao["roles"] == ["operations"] and wanghao["label"] == "王浩 · 运营（运营部）"
    assert next(u for u in users if u["name"] == "赵一鸣")["roles"] == []

    r = client.post("/api/dev/login-as", json={"user_id": wanghao["id"]})
    assert r.status_code == 200 and r.json()["user"]["name"] == "王浩"
    assert client.get("/api/me").json()["auth_source"] == AuthSource.DEV

    r = client.post("/api/auth/dev-login", json={"user_id": user_id(db, "linxiao")})
    assert r.status_code == 200 and r.json()["roles"] == ["finance_head"]

    r = client.post("/api/auth/dev-login", json={"user_id": user_id(db, "zhaoyiming")})
    assert r.status_code == 403
    assert r.json() == {"code": "no_role", "message": NO_ROLE, "details": {"name": "赵一鸣（视觉部）"}}


def test_prod_config_with_dev_switch_fails_to_start():
    with pytest.raises(ConfigError, match="DEV_IDENTITY_SWITCH"):
        load_settings(DATABASE_URL=TEST_DATABASE_URL, APP_ENV="prod", DEV_IDENTITY_SWITCH=True, **DINGTALK_CREDS)
    with pytest.raises(ConfigError, match="钉钉凭据"):
        load_settings(DATABASE_URL=TEST_DATABASE_URL, APP_ENV="prod", DEV_IDENTITY_SWITCH=False)


def test_prod_has_no_dev_routes_and_rejects_dev_sessions(seeded, db, dingtalk):
    prod = build_client(db, dingtalk, APP_ENV="prod", DEV_IDENTITY_SWITCH=False)
    assert prod.get("/api/auth/config").json()["dev_switch"] is False
    assert prod.get("/api/auth/dev-users").status_code == 404
    assert prod.post("/api/dev/login-as", json={"user_id": 1}).status_code == 404
    assert prod.post("/api/auth/dev-login", json={"user_id": 1}).status_code == 404

    user = db.get(User, user_id(db, "linxiao"))
    token = create_session(db, user, AuthSource.DEV, make_settings())
    prod.cookies.set(SESSION_COOKIE, token)
    assert prod.get("/api/me").status_code == 401
    prod.cookies.clear()
    assert prod.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-linxiao"}).status_code == 200
    assert prod.get("/api/me").json()["auth_source"] == AuthSource.DINGTALK


def test_cross_site_write_rejected(seeded, client):
    r = client.post("/api/auth/logout", headers={"Origin": "http://evil.example.com"})
    assert r.status_code == 403 and r.json() == {"code": "forbidden", "message": "无权限"}
