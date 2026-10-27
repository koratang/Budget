"""钉钉开放平台本地替身（独立 FastAPI 进程，端口 8090）。

后端配置 DINGTALK_BASE_URL=http://127.0.0.1:8090 即全部指向本替身。模拟：
- 企业凭证、扫码登录、H5 免登（code = h5-<userid>）
  · 内嵌模式 /oauth2/auth?iframe=true：渲染本地生成的二维码与「模拟扫码」员工列表；点选员工即视为该员工扫码确认，
    以 postMessage 向父页面（redirect_uri 的源）回传临时登录码 tmp-<userid>
  · 父页面带 loginTmpCode 打开 /oauth2/auth → 替身按临时码换取 authCode=qr-<userid>，302 到 redirect_uri
  · 不带 iframe / loginTmpCode 时为整页扫码页（点选员工直接回调）
- 通讯录（可停用 / 移除用户）、工作通知（可配置对某些接收人返回 errcode ≠ 0）
管理接口（/_stub/*）：GET messages 查看已收到通知；users 增改删；fail-receivers 设置失败接收人；reset 复位。
"""
import html
import itertools
import json
import threading
from datetime import datetime
from urllib.parse import urlencode, urlsplit

import segno

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from scripts.seed_data import PEOPLE

CORP_TOKEN = "stub-corp-access-token"
ROOT_DEPT = 1
FAIL_ERRCODE = 40035

app = FastAPI(title="钉钉替身")
_lock = threading.Lock()
_task_ids = itertools.count(1001)


def _default_users() -> dict[str, dict]:
    return {uid: {"userid": uid, "name": name, "dept_name": dept, "active": True, "unionid": f"union-{uid}"}
            for uid, name, dept, *_ in PEOPLE}


state: dict = {"users": _default_users(), "messages": [], "fail_receivers": set()}


def _ok(**kw) -> dict:
    return {"errcode": 0, "errmsg": "ok", **kw}


def _err(code: int, msg: str) -> dict:
    return {"errcode": code, "errmsg": msg}


def _check_token(access_token: str | None) -> dict | None:
    return None if access_token == CORP_TOKEN else _err(40014, "不合法的access_token")


def _depts() -> list[str]:
    return sorted({u["dept_name"] for u in state["users"].values()})


def _dept_id(name: str) -> int:
    return _depts().index(name) + 2


def _user_json(u: dict) -> dict:
    return {"userid": u["userid"], "name": u["name"], "active": u["active"], "unionid": u["unionid"],
            "dept_name": u["dept_name"], "dept_id_list": [_dept_id(u["dept_name"])]}


# ---------------------------------------------------------------------------
# 钉钉接口
# ---------------------------------------------------------------------------
@app.post("/v1.0/oauth2/accessToken")
def corp_access_token(body: dict):
    return {"accessToken": CORP_TOKEN, "expireIn": 7200}


TMP_PREFIX = "tmp-"
EMBED_PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>钉钉扫码登录（替身）</title>
<style>
body{{margin:0;font:13px/1.5 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#1f2329;background:#fff;text-align:center}}
.qr{{display:inline-block;margin:8px 0 4px}} .qr svg{{display:block}}
.tip{{margin:0 0 8px;color:#646a73}} .stub{{border-top:1px dashed #c9cdd4;margin:0 8px;padding-top:6px;text-align:left}}
.stub b{{font-size:12px;color:#646a73;font-weight:500}} ul{{list-style:none;margin:4px 0 0;padding:0;max-height:96px;overflow:auto}}
li button{{width:100%;text-align:left;border:0;background:none;padding:2px 4px;font:inherit;color:#1f2329;cursor:pointer}}
li button:hover{{background:#f2f3f5}}
</style>
<div class="qr" role="img" aria-label="钉钉扫码登录二维码">{qr}</div>
<p class="tip">请使用钉钉 App 扫码登录</p>
<div class="stub"><b>模拟扫码（替身）</b><ul>{items}</ul></div>
<script>
const TARGET = {target};
document.querySelectorAll('button[data-tmp]').forEach((b) => b.addEventListener('click', () => {{
  window.parent.postMessage(b.dataset.tmp, TARGET);
}}));
</script></html>"""


def _origin(url: str) -> str:
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


@app.get("/oauth2/auth", response_class=HTMLResponse)
def qr_page(request: Request, redirect_uri: str):
    """扫码授权页。内嵌模式（iframe=true）回传临时登录码；带 loginTmpCode 时换取 authCode 并回调；否则为整页扫码。"""
    st = request.query_params.get("state", "")
    tmp = request.query_params.get("loginTmpCode")
    if tmp is not None:
        userid = tmp.removeprefix(TMP_PREFIX)
        if not tmp.startswith(TMP_PREFIX) or userid not in state["users"]:
            return HTMLResponse("临时登录码无效或已过期", status_code=400)
        return RedirectResponse(f"{redirect_uri}?{urlencode({'authCode': 'qr-' + userid, 'state': st})}",
                                status_code=302)
    if request.query_params.get("iframe") == "true":
        qr = segno.make(str(request.url), error="m").svg_inline(scale=4, border=2, dark="#1f2329")
        items = "".join(
            f'<li><button type="button" data-tmp="{html.escape(TMP_PREFIX + u["userid"])}">'
            f'{html.escape(u["name"])}（{html.escape(u["dept_name"])}{"，已停用" if not u["active"] else ""}）</button></li>'
            for u in state["users"].values())
        return EMBED_PAGE.format(qr=qr, items=items, target=json.dumps(_origin(redirect_uri)))
    items = "".join(
        f'<li><a href="{html.escape(redirect_uri)}?{urlencode({"authCode": "qr-" + u["userid"], "state": st})}">'
        f'{html.escape(u["name"])}（{html.escape(u["dept_name"])}{"，已停用" if not u["active"] else ""}）</a></li>'
        for u in state["users"].values())
    return f"<!doctype html><meta charset='utf-8'><title>钉钉扫码（替身）</title><h3>选择扫码员工</h3><ul>{items}</ul>"


@app.post("/v1.0/oauth2/userAccessToken")
def user_access_token(body: dict):
    code = body.get("code", "")
    userid = code.removeprefix("qr-")
    if not code.startswith("qr-") or userid not in state["users"]:
        return JSONResponse({"code": "invalidAuthCode", "message": "授权码无效"}, status_code=400)
    return {"accessToken": f"uat-{userid}", "refreshToken": "", "expireIn": 7200}


@app.get("/v1.0/contact/users/me")
def users_me(x_acs_dingtalk_access_token: str = Header(...)):
    userid = x_acs_dingtalk_access_token.removeprefix("uat-")
    u = state["users"].get(userid)
    if u is None:
        return JSONResponse({"code": "invalidToken", "message": "token 无效"}, status_code=401)
    return {"unionId": u["unionid"], "nick": u["name"]}


@app.post("/topapi/user/getbyunionid")
def get_by_unionid(body: dict, access_token: str | None = None):
    if err := _check_token(access_token):
        return err
    for u in state["users"].values():
        if u["unionid"] == body.get("unionid"):
            return _ok(result={"userid": u["userid"], "contact_type": 0})
    return _err(60121, "找不到该用户")


@app.post("/topapi/v2/user/getuserinfo")
def h5_userinfo(body: dict, access_token: str | None = None):
    if err := _check_token(access_token):
        return err
    code = body.get("code", "")
    userid = code.removeprefix("h5-")
    if not code.startswith("h5-") or userid not in state["users"]:
        return _err(40078, "不存在的临时授权码")
    return _ok(result={"userid": userid, "name": state["users"][userid]["name"]})


@app.post("/topapi/v2/user/get")
def user_get(body: dict, access_token: str | None = None):
    if err := _check_token(access_token):
        return err
    u = state["users"].get(body.get("userid"))
    if u is None:
        return _err(60121, "找不到该用户")
    return _ok(result=_user_json(u))


@app.post("/topapi/v2/department/listsub")
def dept_listsub(body: dict, access_token: str | None = None):
    if err := _check_token(access_token):
        return err
    if body.get("dept_id") != ROOT_DEPT:
        return _ok(result=[])
    return _ok(result=[{"dept_id": _dept_id(n), "name": n, "parent_id": ROOT_DEPT} for n in _depts()])


@app.post("/topapi/v2/user/list")
def user_list(body: dict, access_token: str | None = None):
    if err := _check_token(access_token):
        return err
    dept = body.get("dept_id")
    users = [_user_json(u) for u in state["users"].values() if _dept_id(u["dept_name"]) == dept]
    return _ok(result={"has_more": False, "next_cursor": 0, "list": users})


@app.post("/topapi/message/corpconversation/asyncsend_v2")
def send_notice(body: dict, access_token: str | None = None):
    if err := _check_token(access_token):
        return err
    receivers = [r for r in str(body.get("userid_list", "")).split(",") if r]
    failed = sorted(set(receivers) & state["fail_receivers"])
    with _lock:
        record = {"id": len(state["messages"]) + 1, "at": datetime.now().isoformat(timespec="seconds"),
                  "agent_id": body.get("agent_id"), "userid_list": receivers, "msg": body.get("msg"),
                  "errcode": FAIL_ERRCODE if failed else 0}
        if not failed:
            record["task_id"] = next(_task_ids)
        state["messages"].append(record)
    if failed:
        return _err(FAIL_ERRCODE, f"接收人不合法：{','.join(failed)}")
    return _ok(task_id=record["task_id"], request_id=f"stub-{record['id']}")


# ---------------------------------------------------------------------------
# 替身管理接口
# ---------------------------------------------------------------------------
@app.get("/_stub/messages")
def stub_messages():
    return state["messages"]


@app.delete("/_stub/messages")
def stub_clear_messages():
    state["messages"].clear()
    return {"ok": True}


@app.get("/_stub/users")
def stub_users():
    return list(state["users"].values())


class StubUser(BaseModel):
    userid: str
    name: str
    dept_name: str = "视觉部"
    active: bool = True


@app.post("/_stub/users")
def stub_add_user(body: StubUser):
    state["users"][body.userid] = {**body.model_dump(), "unionid": f"union-{body.userid}"}
    return state["users"][body.userid]


class ActiveIn(BaseModel):
    active: bool


@app.patch("/_stub/users/{userid}")
def stub_set_active(userid: str, body: ActiveIn):
    u = state["users"].get(userid)
    if u is None:
        return JSONResponse({"detail": "not found"}, status_code=404)
    u["active"] = body.active
    return u


@app.delete("/_stub/users/{userid}")
def stub_remove_user(userid: str):
    """模拟移出企业通讯录。"""
    return {"removed": state["users"].pop(userid, None) is not None}


class FailIn(BaseModel):
    userids: list[str]


@app.put("/_stub/fail-receivers")
def stub_fail_receivers(body: FailIn):
    state["fail_receivers"] = set(body.userids)
    return {"fail_receivers": sorted(state["fail_receivers"])}


@app.get("/_stub/h5-code")
def stub_h5_code(userid: str):
    """取工作台免登授权码（真实环境由 dingtalk-jsapi 在钉钉内获取）。"""
    return {"code": f"h5-{userid}"}


@app.post("/_stub/reset")
def stub_reset():
    state["users"] = _default_users()
    state["messages"] = []
    state["fail_receivers"] = set()
    return {"ok": True}
