"""G2 场景测试共用：开发身份登录、发布任务、取单位与表格行、读钉钉替身通知。"""
from __future__ import annotations

from sqlalchemy import select

from app.dingtalk.outbox import process_outbox
from app.models import (BCustomer, BudgetAccount, Category, Channel, Department, FillingUnit, Site, Store, User,
                        UserRole, UserScope)

YEAR = 2027
DEADLINE = "2026-12-20"


def uid(db, userid: str) -> int:
    return db.scalar(select(User.id).where(User.dingtalk_userid == userid))


def login(client, db, userid: str) -> None:
    r = client.post("/api/dev/login-as", json={"user_id": uid(db, userid)})
    assert r.status_code == 200, r.text


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


def store(db, name: str) -> Store:
    return db.scalar(select(Store).where(Store.name == name))


def dept(db, name: str) -> Department:
    return db.scalar(select(Department).where(Department.name == name))


def account(db, name: str) -> BudgetAccount:
    return db.scalar(select(BudgetAccount).where(BudgetAccount.name == name))


def customer(db, name: str) -> BCustomer:
    return db.scalar(select(BCustomer).where(BCustomer.name == name))


def category_id(db, name: str) -> int:
    return db.scalar(select(Category.id).where(Category.name == name))


def channel_id(db, name: str) -> int:
    return db.scalar(select(Channel.id).where(Channel.name == name))


def site_id(db, code: str) -> int:
    return db.scalar(select(Site.id).where(Site.code == code))


def minimal_units(db, *, stores=("Amazon-US-01",), b2b_depts=("美国业务部",), depts=("人力资源部",),
                  cost=True, logistics=True) -> list[dict]:
    units = [{"unit_type": "platform", "scope_object_id": store(db, s).id} for s in stores]
    units += [{"unit_type": "b2b", "scope_object_id": dept(db, d).id} for d in b2b_depts]
    if cost:
        units.append({"unit_type": "cost_ratio", "scope_object_id": None})
    if logistics:
        units.append({"unit_type": "logistics_ratio", "scope_object_id": None})
    units += [{"unit_type": "dept_expense", "scope_object_id": dept(db, d).id} for d in depts]
    return units


def publish(client, db, units: list[dict] | None = None, *, year: int = YEAR, deadline: str = DEADLINE):
    login(client, db, "linxiao")
    body = {"year": year, "deadline": deadline}
    if units is not None:
        body["units"] = units
    return client.post("/api/tasks", json=body)


def unit_by_name(db, task_id: int, name: str) -> FillingUnit:
    return db.scalar(select(FillingUnit).where(FillingUnit.task_id == task_id, FillingUnit.name == name))


def grid(client, unit_id: int, tab: str | None = None) -> dict:
    r = client.get(f"/api/filling-units/{unit_id}/grid", params={"tab": tab} if tab else None)
    assert r.status_code == 200, r.text
    return r.json()


def row(g: dict, key: str) -> dict:
    return next(r for r in g["rows"] if r["key"] == key)


def pu_key(db, store_name: str, category: str, is_new: bool, item: str) -> str:
    s = store(db, store_name)
    return f"pu:{s.id}:{s.site_id}:{category_id(db, category)}:{1 if is_new else 0}|{item}"


def save(client, unit_id: int, changes: list[tuple[str, str, str]], g: dict | None = None, tab: str | None = None):
    """changes = [(row_key, 'YYYY-MM', value)]；基准值取自给定表格（缺省先读一次）。"""
    g = g or grid(client, unit_id, tab)
    body = []
    for key, field, value in changes:
        base = next((r["values"].get(field) for r in g["rows"] if r["key"] == key), None)
        body.append({"row_key": key, "field": field, "value": value, "base": base})
    return client.patch(f"/api/filling-units/{unit_id}/cells", json=body, params={"tab": tab} if tab else None)


def submit(client, unit_id: int):
    return client.post(f"/api/filling-units/{unit_id}/submit")


def messages(db, dingtalk, stub) -> list[dict]:
    process_outbox(db, dingtalk)
    return stub.get("/_stub/messages").json()


def to_receiver(msgs: list[dict], userid: str) -> list[dict]:
    return [m for m in msgs if userid in m["userid_list"]]

