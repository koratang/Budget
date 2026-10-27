"""FLOW-01 验收（API 层，真实路由 + 数据库 + 钉钉替身）：期望值逐字取自 TDD验收契约 FLOW-01。

①王浩经扫码回调与工作台免登进入：/api/me 显示「王浩」与角色名称「运营」，建立 HttpOnly 会话；
②赵一鸣（通讯录有、无角色）：停留登录页并显示「未开通预算权限，请联系财务负责人」，不建会话；
③王浩登录后在通讯录被停用，同步后下一次请求 401 并显示「无法登录：钉钉账号已停用或不在企业通讯录中」，再次扫码同样被拒；
④从通知链接 /reports/channel-site?month=2027-04 未登录进入，登录后回到原链接；系统无账号密码登录入口。
"""
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import func, select

from app.core.auth import SESSION_COOKIE
from app.dingtalk.scheduler import run_contact_sync
from app.models import UserSession
from tests.acceptance.e1_helpers import uid
from tests.conftest import build_client

NO_ROLE = "未开通预算权限，请联系财务负责人"
DISABLED = "无法登录：钉钉账号已停用或不在企业通讯录中"
LINK = "/reports/channel-site?month=2027-04"


def _qr(c, userid, state=None):
    params = {"authCode": f"qr-{userid}"}
    if state:
        params["state"] = state
    return c.get("/api/auth/dingtalk/callback", params=params, follow_redirects=False)


def test_flow_01_qr_and_h5_enter(seeded, dingtalk):
    db = seeded
    c = build_client(db, dingtalk)
    # 扫码地址指向钉钉（替身）扫码页
    url = c.get("/api/auth/dingtalk/qr-url").json()["url"]
    assert url.startswith("http://dingtalk-stub.local/oauth2/auth")
    r = _qr(c, "wanghao")
    assert r.status_code == 302 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=") and "HttpOnly" in cookie
    me = c.get("/api/me").json()
    assert me["user"]["name"] == "王浩" and me["role_names"] == ["运营"]
    # 工作台免登
    c2 = build_client(db, dingtalk)
    r = c2.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-wanghao"})
    assert r.status_code == 200 and "HttpOnly" in r.headers["set-cookie"]
    me = c2.get("/api/me").json()
    assert me["user"]["name"] == "王浩" and me["role_names"] == ["运营"]
    assert c2.get("/api/workbench").status_code == 200


def test_flow_01_no_role(seeded, dingtalk):
    db = seeded
    c = build_client(db, dingtalk)
    r = _qr(c, "zhaoyiming")
    loc = urlsplit(r.headers["location"])
    assert loc.path == "/login" and parse_qs(loc.query)["error"] == ["no_role"]
    assert "set-cookie" not in r.headers
    r = c.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-zhaoyiming"})
    assert r.status_code == 403 and r.json()["message"] == NO_ROLE
    assert "set-cookie" not in r.headers
    assert db.scalar(select(func.count()).select_from(UserSession)
                     .where(UserSession.user_id == uid(db, "zhaoyiming"))) == 0
    assert c.get("/api/me").status_code == 401


def test_flow_01_disabled_after_login(seeded, dingtalk, stub):
    db = seeded
    c = build_client(db, dingtalk)
    assert _qr(c, "wanghao").status_code == 302
    assert c.get("/api/me").status_code == 200
    assert stub.patch("/_stub/users/wanghao", json={"active": False}).status_code == 200
    run_contact_sync(db, dingtalk)
    r = c.get("/api/me")
    assert r.status_code == 401 and r.json()["message"] == DISABLED
    r = _qr(c, "wanghao")
    assert parse_qs(urlsplit(r.headers["location"]).query)["error"] == ["account_disabled"]
    assert "set-cookie" not in r.headers
    r = c.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-wanghao"})
    assert r.json()["message"] == DISABLED and "set-cookie" not in r.headers


def test_flow_01_return_to_link_and_no_password_login(seeded, dingtalk):
    db = seeded
    c = build_client(db, dingtalk)
    assert c.get("/api/me").status_code == 401
    url = c.get("/api/auth/dingtalk/qr-url", params={"redirect": LINK}).json()["url"]
    assert parse_qs(urlsplit(url).query)["state"] == [LINK]
    r = _qr(c, "wanghao", state=LINK)
    assert r.status_code == 302 and r.headers["location"] == LINK
    paths = {p for p in c.get("/api/openapi.json").json()["paths"]}
    assert not any("password" in p or p.endswith("/auth/login") for p in paths), paths
    assert c.post("/api/auth/login", json={"username": "wanghao", "password": "x"}).status_code == 404
