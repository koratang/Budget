"""FLOW-01 钉钉登录（REQ-F01-01，AC-F01-01~03）：本机用钉钉替身验证，期望值逐字取自 TDD验收契约 FLOW-01。

① 王浩（运营）经扫码回调与工作台免登进入：显示「王浩」与角色名称「运营」，建立 HttpOnly 会话
② 赵一鸣（无角色）：停留登录页并显示「未开通预算权限，请联系财务负责人」，不建会话
③ 王浩登录后被停用并同步通讯录：下一次请求 401，显示「无法登录：钉钉账号已停用或不在企业通讯录中」，再次扫码同样被拒
④ 从通知链接 /reports/channel-site?month=2027-04 未登录进入：登录后回到原链接；系统无账号密码登录入口
"""
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from app.core.auth import SESSION_COOKIE
from app.dingtalk.scheduler import run_contact_sync
from app.models import UserSession
from tests.g1.helpers import uid

NO_ROLE = "未开通预算权限，请联系财务负责人"
DISABLED = "无法登录：钉钉账号已停用或不在企业通讯录中"
LINK = "/reports/channel-site?month=2027-04"


def _qr(client, userid, state=None):
    params = {"authCode": f"qr-{userid}"}
    if state:
        params["state"] = state
    return client.get("/api/auth/dingtalk/callback", params=params, follow_redirects=False)


def test_role_holder_enters_by_qr_and_h5(seeded, client, db):
    r = _qr(client, "wanghao")
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert r.headers["set-cookie"].startswith(f"{SESSION_COOKIE}=") and "HttpOnly" in r.headers["set-cookie"]
    me = client.get("/api/me").json()
    assert me["user"]["name"] == "王浩" and me["role_names"] == ["运营"]

    client.cookies.clear()
    r = client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-wanghao"})
    assert r.status_code == 200 and "HttpOnly" in r.headers["set-cookie"]
    me = client.get("/api/me").json()
    assert me["user"]["name"] == "王浩" and me["role_names"] == ["运营"]


def test_no_role_stays_on_login(seeded, client, db):
    r = _qr(client, "zhaoyiming")
    loc = urlsplit(r.headers["location"])
    assert loc.path == "/login" and parse_qs(loc.query)["error"] == ["no_role"]
    assert "set-cookie" not in r.headers
    r = client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-zhaoyiming"})
    assert r.status_code == 403 and r.json()["message"] == NO_ROLE
    assert db.scalar(select(UserSession).where(UserSession.user_id == uid(db, "zhaoyiming"))) is None


def test_disabled_after_login(seeded, client, stub, dingtalk, db):
    assert _qr(client, "wanghao").status_code == 302
    assert client.get("/api/me").status_code == 200
    stub.patch("/_stub/users/wanghao", json={"active": False})
    run_contact_sync(db, dingtalk)
    r = client.get("/api/me")
    assert r.status_code == 401 and r.json()["message"] == DISABLED
    r = _qr(client, "wanghao")
    assert parse_qs(urlsplit(r.headers["location"]).query)["error"] == ["account_disabled"]
    assert "set-cookie" not in r.headers


def test_notification_link_returns_after_login_and_no_password_login(seeded, client):
    assert client.get("/api/me").status_code == 401
    r = _qr(client, "wanghao", state=LINK)
    assert r.headers["location"] == LINK
    paths = {getattr(route, "path", "") for route in client.app.routes}
    assert not any("password" in p or p.endswith("/auth/login") for p in paths)
