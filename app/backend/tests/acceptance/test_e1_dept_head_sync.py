"""部门负责人（审核人）跟随角色与权限（主控裁定的产品缺陷修复回归）：真实路由 + 数据库。

在角色与权限分配「部门负责人 · 市场部」→ 该员工成为市场部审核人；改派新负责人后未审结单位转给新负责人、原负责人不能再审；
撤销新负责人 → 改由该部门其余负责人担任；无负责人角色的员工保存角色不影响其所任部门负责人（如林晓 · 财务部）。
"""
from sqlalchemy import select

from app.models import Department, FillingUnit, User
from tests.acceptance.e1_helpers import DEADLINE, People, add_user


def _dept(db, name):
    return db.scalar(select(Department).where(Department.name == name))


def test_dept_head_follows_role_assignment(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    lin = p("linxiao")
    mkt = _dept(db, "市场部")
    add_user(db, "e1-denglin", "邓琳", "市场部", ["dept_budget"], {"department": [mkt.id]})
    kl = add_user(db, "e1-kongliang", "孔亮", "市场部", [])
    sy = add_user(db, "e1-songyan", "宋岩", "市场部", [])
    assert mkt.head_user_id is None

    r = lin.put(f"/api/admin/users/{kl.id}/roles", json={"roles": ["dept_head"], "departments": [mkt.id]})
    assert r.status_code == 200, r.text
    assert _dept(db, "市场部").head_user_id == kl.id

    cand = next(c for c in lin.get("/api/tasks/candidates").json()["items"] if c["name"] == "市场部")
    assert cand["reviewer"]["name"] == "孔亮"
    r = lin.post("/api/tasks", json={"year": 2027, "deadline": DEADLINE,
                                     "units": [{"unit_type": "dept_expense", "scope_object_id": mkt.id}]})
    assert r.status_code == 201, r.text
    unit = db.scalar(select(FillingUnit).where(FillingUnit.task_id == r.json()["task"]["id"]))
    assert unit.reviewer_id == kl.id
    dl = p("e1-denglin")
    g = dl.get(f"/api/dept-expense/{unit.id}/grid").json()
    row = next(x for x in g["rows"] if x.get("kind") == "input")
    assert dl.patch(f"/api/filling-units/{unit.id}/cells", json=[{"row_key": row["key"], "field": "2027-01",
                                                                  "value": "1000", "base": row["values"]["2027-01"]}]
                    ).status_code == 200
    assert dl.post(f"/api/filling-units/{unit.id}/submit").status_code == 200

    # 改派宋岩为市场部负责人：未审结单位的审核人随之改为宋岩，孔亮不能再审
    r = lin.put(f"/api/admin/users/{sy.id}/roles", json={"roles": ["dept_head"], "departments": [mkt.id]})
    assert r.status_code == 200, r.text
    db.refresh(unit)
    assert _dept(db, "市场部").head_user_id == sy.id and unit.reviewer_id == sy.id
    assert p("e1-kongliang").post(f"/api/approvals/unit/{unit.id}/approve").status_code in (403, 409)
    pending = p("e1-songyan").get("/api/approvals").json()
    assert any(it["type"] == "unit" and it["id"] == unit.id for it in pending["items"]), pending

    # 撤销宋岩：改由仍持有「部门负责人 · 市场部」的孔亮担任
    r = lin.put(f"/api/admin/users/{sy.id}/roles", json={"roles": []})
    assert r.status_code == 200, r.text
    db.refresh(unit)
    assert _dept(db, "市场部").head_user_id == kl.id and unit.reviewer_id == kl.id
    assert p("e1-kongliang").post(f"/api/approvals/unit/{unit.id}/approve").status_code == 200

    # 撤销最后一位负责人：部门负责人空缺，发布时该部门单位列为缺审核人
    r = lin.put(f"/api/admin/users/{kl.id}/roles", json={"roles": []})
    assert r.status_code == 200, r.text
    assert _dept(db, "市场部").head_user_id is None
    cand = next(c for c in lin.get("/api/tasks/candidates").json()["items"] if c["name"] == "市场部")
    assert cand["reviewer"] is None

    # 无负责人角色的员工保存角色：林晓仍为财务部负责人
    fin_head = _dept(db, "财务部").head_user_id
    assert db.get(User, fin_head).name == "林晓"
    bp_id = db.scalar(select(User.id).where(User.name == "陈思雨"))
    assert lin.put(f"/api/admin/users/{bp_id}/roles", json={"roles": ["finance_bp"]}).status_code == 200
    assert _dept(db, "财务部").head_user_id == fin_head
