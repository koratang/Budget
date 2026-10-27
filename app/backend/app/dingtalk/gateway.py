"""钉钉网关 CMP-F11-02（技术方案 §4.6）。

出站 HTTP 只允许配置的钉钉服务端地址（DINGTALK_BASE_URL / DINGTALK_OAPI_BASE_URL，默认官方域名），
其他主机直接抛错（NFR-005）。接口路径基于钉钉开放平台公开文档，上线前须按官方文档逐一核对（§2.4）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import httpx

from app.config import Settings

# 钉钉「找不到该用户」等错误码：视为不在通讯录
_USER_NOT_FOUND_CODES = {60121, 60111, 33012}


class DingTalkError(RuntimeError):
    """钉钉调用失败（网络错误、HTTP 非 200 或 errcode ≠ 0）。"""

    def __init__(self, message: str, errcode: int | None = None):
        super().__init__(message)
        self.errcode = errcode


class DingTalkAuthError(DingTalkError):
    """授权码无效或已过期。"""


class HostNotAllowed(RuntimeError):
    """出站目标不在钉钉白名单（NFR-005）。"""


@dataclass(frozen=True)
class DirectoryUser:
    userid: str
    name: str
    active: bool
    unionid: str | None = None
    dept_name: str | None = None


class AllowlistTransport(httpx.BaseTransport):
    """在传输层强制主机白名单：即使调用方拼错 URL 也无法连到非钉钉主机。"""

    def __init__(self, allowed_hosts: frozenset[str], inner: httpx.BaseTransport | None = None):
        self.allowed_hosts = allowed_hosts
        self.inner = inner or httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        netloc = request.url.netloc.decode() if isinstance(request.url.netloc, bytes) else request.url.netloc
        if netloc not in self.allowed_hosts:
            raise HostNotAllowed(f"禁止访问非钉钉地址：{request.url.host}")
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


class DingTalkClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None, timeout: float = 10.0):
        self.settings = settings
        self.api = settings.dingtalk_api_url
        self.oapi = settings.dingtalk_oapi_url
        self._http = httpx.Client(transport=AllowlistTransport(settings.dingtalk_allowed_hosts, transport),
                                  timeout=timeout)
        self._token: str | None = None
        self._token_expire_at = 0.0
        self._lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    # ---- 底层 ----
    def _request(self, method: str, url: str, **kw) -> dict:
        try:
            resp = self._http.request(method, url, **kw)
        except HostNotAllowed:
            raise
        except httpx.HTTPError as e:
            raise DingTalkError(f"钉钉网络错误：{type(e).__name__}") from e
        if resp.status_code != 200:
            raise DingTalkError(f"钉钉返回 HTTP {resp.status_code}")
        data = resp.json()
        errcode = data.get("errcode")
        if errcode not in (None, 0):
            raise DingTalkError(f"钉钉返回错误 errcode={errcode}", errcode=errcode)
        return data

    def access_token(self) -> str:
        """企业凭证：进程内缓存，提前 5 分钟刷新。"""
        with self._lock:
            if self._token and time.monotonic() < self._token_expire_at:
                return self._token
            data = self._request("POST", f"{self.api}/v1.0/oauth2/accessToken",
                                 json={"appKey": self.settings.DINGTALK_APP_KEY,
                                       "appSecret": self.settings.DINGTALK_APP_SECRET})
            self._token = data["accessToken"]
            self._token_expire_at = time.monotonic() + max(int(data.get("expireIn", 7200)) - 300, 60)
            return self._token

    def _oapi(self, path: str, body: dict) -> dict:
        return self._request("POST", f"{self.oapi}{path}", params={"access_token": self.access_token()}, json=body)

    # ---- 登录 ----
    def qr_login_url(self, redirect_uri: str, state: str) -> str:
        q = httpx.QueryParams({"redirect_uri": redirect_uri, "response_type": "code",
                               "client_id": self.settings.DINGTALK_APP_KEY or "", "scope": "openid",
                               "state": state, "prompt": "consent"})
        return f"{self.settings.dingtalk_login_url}/oauth2/auth?{q}"

    def userid_from_qr_code(self, auth_code: str) -> str:
        """扫码 OAuth2：authCode → 用户 token → unionId → 企业内 userid。"""
        try:
            tok = self._request("POST", f"{self.api}/v1.0/oauth2/userAccessToken",
                                json={"clientId": self.settings.DINGTALK_APP_KEY,
                                      "clientSecret": self.settings.DINGTALK_APP_SECRET,
                                      "code": auth_code, "grantType": "authorization_code"})
        except DingTalkError as e:
            raise DingTalkAuthError("钉钉授权码无效或已过期") from e
        me = self._request("GET", f"{self.api}/v1.0/contact/users/me",
                           headers={"x-acs-dingtalk-access-token": tok["accessToken"]})
        data = self._oapi("/topapi/user/getbyunionid", {"unionid": me["unionId"]})
        return data["result"]["userid"]

    def userid_from_h5_code(self, auth_code: str) -> str:
        """工作台免登：免登授权码 → userid。"""
        try:
            data = self._oapi("/topapi/v2/user/getuserinfo", {"code": auth_code})
        except DingTalkError as e:
            raise DingTalkAuthError("钉钉免登授权码无效或已过期") from e
        return data["result"]["userid"]

    # ---- 通讯录 ----
    def get_user(self, userid: str) -> DirectoryUser | None:
        """实时取用户详情；不在通讯录返回 None。"""
        try:
            data = self._oapi("/topapi/v2/user/get", {"userid": userid, "language": "zh_CN"})
        except DingTalkError as e:
            if e.errcode in _USER_NOT_FOUND_CODES:
                return None
            raise
        return _directory_user(data["result"])

    def list_users(self) -> list[DirectoryUser]:
        """遍历部门树取全部用户（每 10 分钟增量 / 每日全量同步共用）。"""
        dept_ids, queue = [1], [1]
        while queue:
            dept = queue.pop()
            subs = self._oapi("/topapi/v2/department/listsub", {"dept_id": dept}).get("result") or []
            for d in subs:
                dept_ids.append(d["dept_id"])
                queue.append(d["dept_id"])
        users: dict[str, DirectoryUser] = {}
        for dept in dept_ids:
            cursor = 0
            while True:
                res = self._oapi("/topapi/v2/user/list", {"dept_id": dept, "cursor": cursor, "size": 100})["result"]
                for u in res.get("list", []):
                    users[u["userid"]] = _directory_user(u)
                if not res.get("has_more"):
                    break
                cursor = res["next_cursor"]
        return list(users.values())

    # ---- 工作通知 ----
    def send_work_notice(self, userids: list[str], msg: dict) -> str:
        data = self._oapi("/topapi/message/corpconversation/asyncsend_v2",
                          {"agent_id": self.settings.DINGTALK_AGENT_ID, "userid_list": ",".join(userids),
                           "msg": msg})
        return str(data.get("task_id", ""))


def _directory_user(u: dict) -> DirectoryUser:
    return DirectoryUser(userid=u["userid"], name=u.get("name", ""), active=bool(u.get("active", True)),
                         unionid=u.get("unionid"), dept_name=u.get("dept_name"))
