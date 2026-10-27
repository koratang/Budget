"""E1 验收（SMOKE-03、FLOW-01~10）共用：场景前置主数据、每人独立 Cookie 的客户端、常用接口操作。

前置只写契约「场景与操作」中的初始状态（主数据与人员）；待验动作一律经真实 HTTP 路由完成。
"""
from __future__ import annotations

import io
from contextlib import nullcontext

from openpyxl import Workbook
from sqlalchemy import select, update

from app.dingtalk.outbox import process_outbox
from app.models import BCustomer, Department, Store, User, UserRole, UserScope
from tests.conftest import build_client

DEADLINE = "2026-12-20"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

FLOW09_ACTIVE_STORES = ("Amazon-US-01", "Amazon-CA-01", "Wayfair-US-01", "Shopify-US-01", "TikTok-US-01")
# 15 个参与部门各需部门预算专员与部门负责人（种子只有人力资源部专员）：(专员, 负责人或 None=已有)
FLOW09_PEOPLE = {
    "产品作战部": ("许嘉", "沈卓"), "开发部": ("宋宇", "顾磊"), "研发部": ("韩冰", "钱峰"), "供应中心": ("冯涛", "陆军"),
    "运营部": ("曹敏", None), "市场部": ("邓琳", "孔亮"), "美国业务部": ("周凯", None), "视觉部": ("彭悦", "范婷"),
    "外贸部": ("江涛", None), "物流物控部": ("吕彬", None), "项目管理部": ("唐瑶", "黎明"),
    "信息数字化部": ("董杰", "邵阳"), "财务部": ("郭琪", None), "总经办": ("袁芳", None),
}


def add_user(db, userid: str, name: str, dept: str, roles: list[str], scopes: dict | None = None,
             head: bool = False) -> User:
    d = db.scalar(select(Department).where(Department.name == dept))
    u = User(dingtalk_userid=userid, name=name, union_id=f"union-{userid}", dingtalk_dept=dept, department_id=d.id,
             is_active=True)
    db.add(u)
    db.flush()
    for r in roles:
        db.add(UserRole(user_id=u.id, role_code=r))
    for scope_type, ids in (scopes or {}).items():
        for oid in ids:
            db.add(UserScope(user_id=u.id, scope_type=scope_type, object_id=oid))
    if head:
        d.head_user_id = u.id
    db.flush()
    return u


def smoke03_master(db) -> None:
    """SMOKE-03 最小种子：1 个启用店铺 Amazon-US-01、USD 2027 预算汇率 7.12（种子已有）、1 个参与部门（人力资源部），
    B端（美国业务部）/成本比例/物流比例单位与对应人员（种子已有）。"""
    db.execute(update(Store).where(Store.name != "Amazon-US-01").values(is_active=False))
    db.execute(update(Department).where(Department.name != "人力资源部").values(is_active=False))
    db.execute(update(BCustomer).where(BCustomer.name == "Bauhaus").values(is_active=False))
    db.flush()


def flow09_master(db) -> None:
    """FLOW-09：5 个启用店铺 + 1 个停用店铺（Lowes-US-02）、美国业务部与外贸部各有启用客户、15 个参与部门。"""
    db.execute(update(Store).where(Store.name.not_in(FLOW09_ACTIVE_STORES)).values(is_active=False))
    for i, (dept, (budget_name, head_name)) in enumerate(FLOW09_PEOPLE.items()):
        d = db.scalar(select(Department).where(Department.name == dept))
        add_user(db, f"e1-budget-{i}", budget_name, dept, ["dept_budget"], {"department": [d.id]})
        if head_name:
            add_user(db, f"e1-head-{i}", head_name, dept, ["dept_head"], {"department": [d.id]}, head=True)
    db.flush()


def uid(db, userid: str) -> int:
    return db.scalar(select(User.id).where(User.dingtalk_userid == userid))


class People:
    """每人一个独立 Cookie 的真实路由客户端（开发身份 /api/dev/login-as）。"""

    def __init__(self, db, dingtalk, tmp_path=None):
        self.db, self.dingtalk, self.tmp = db, dingtalk, tmp_path
        self._c = {}

    def __call__(self, userid: str):
        if userid not in self._c:
            extra = {"DATA_DIR": str(self.tmp / "data")} if self.tmp else {}
            c = build_client(self.db, self.dingtalk, **extra)
            c.app.state.import_session_factory = lambda: nullcontext(self.db)
            r = c.post("/api/dev/login-as", json={"user_id": uid(self.db, userid)})
            assert r.status_code == 200, r.text
            self._c[userid] = c
        return self._c[userid]

    def reset(self):
        self._c.clear()


def grid(client, unit_id: int, tab: str | None = None) -> dict:
    r = client.get(f"/api/filling-units/{unit_id}/grid", params={"tab": tab} if tab else None)
    assert r.status_code == 200, r.text
    return r.json()


def row(g: dict, key: str) -> dict:
    return next(r for r in g["rows"] if r["key"] == key)


def save(client, unit_id: int, changes: list[tuple[str, str, str]], tab: str | None = None):
    g = grid(client, unit_id, tab)
    body = []
    for key, field, value in changes:
        base = next((r["values"].get(field) for r in g["rows"] if r["key"] == key), None)
        body.append({"row_key": key, "field": field, "value": value, "base": base})
    return client.patch(f"/api/filling-units/{unit_id}/cells", json=body, params={"tab": tab} if tab else None)


def messages(db, dingtalk, stub) -> list[dict]:
    process_outbox(db, dingtalk)
    return stub.get("/_stub/messages").json()


def xlsx(header: list, rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
