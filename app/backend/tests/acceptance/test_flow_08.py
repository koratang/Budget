"""FLOW-08 验收（API 层，真实路由 + 数据库）：期望值逐字取自 TDD验收契约 FLOW-08。

陈思雨新增 B 端客户「Floor & Decor」（负责部门美国业务部、结算币种 USD），孙婷打开美国业务部 B 端填报 → 出现 Floor & Decor 客户组
（6 个输入项），刘洋打开外贸部 B 端填报 → 不出现；重名客户保存提示「客户名称不能重复」。
不做额外的客户范围分配：新客户自动纳入其负责部门 B 端填报（孙婷可见可填）。
"""
from sqlalchemy import func, select

from app.models import BCustomer, Department
from tests.acceptance.e1_helpers import DEADLINE, People

SIX = {"销售额（USD）", "退款率", "推广费用率", "其他运营费用率", "平台佣金率", "库存索赔率"}


def _b2b_grid(c):
    mine = [u for u in c.get("/api/filling-units", params={"mine": 1}).json()["items"] if u["unit_type"] == "b2b"]
    assert len(mine) == 1, mine
    r = c.get(f"/api/filling-units/{mine[0]['id']}/grid")
    assert r.status_code == 200, r.text
    return r.json()


def test_flow_08(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    bp, lin = p("chensiyu"), p("linxiao")
    us_dept = db.scalar(select(Department.id).where(Department.name == "美国业务部"))
    trade = db.scalar(select(Department.id).where(Department.name == "外贸部"))
    r = bp.post("/api/master/b-customers", json={"name": "Floor & Decor", "department_id": us_dept, "currency": "USD"})
    assert r.status_code == 201, r.text
    count = db.scalar(select(func.count()).select_from(BCustomer))
    r = bp.post("/api/master/b-customers", json={"name": "Floor & Decor", "department_id": trade, "currency": "EUR"})
    assert r.status_code == 422 and r.json()["message"] == "客户名称不能重复"
    assert db.scalar(select(func.count()).select_from(BCustomer)) == count

    cands = lin.get("/api/tasks/candidates").json()["items"]
    units = [{"unit_type": c["unit_type"], "scope_object_id": c["scope_object_id"]} for c in cands
             if c["unit_type"] == "b2b"]
    assert len(units) == 2
    r = lin.post("/api/tasks", json={"year": 2027, "deadline": DEADLINE, "units": units})
    assert r.status_code == 201, r.text

    sun = p("sunting")
    g = _b2b_grid(sun)
    fd = [row for row in g["rows"] if row["values"].get("customer") == "Floor & Decor" and row.get("kind") == "input"]
    assert {row["values"]["item"] for row in fd} == SIX, [row["values"]["item"] for row in fd]
    assert len(fd) == 6
    key = next(row["key"] for row in fd if row["key"].endswith("|sales_local"))
    assert all("2027-03" not in (row.get("readonly_fields") or []) for row in fd)
    unit_id = next(u["id"] for u in sun.get("/api/filling-units", params={"mine": 1}).json()["items"]
                   if u["unit_type"] == "b2b")
    r = sun.patch(f"/api/filling-units/{unit_id}/cells", json=[{"row_key": key, "field": "2027-03", "value": "50000",
                                                                 "base": next(x for x in fd if x["key"] == key)["values"]["2027-03"]}])
    assert r.status_code == 200 and r.json()["errors"] == [], r.text
    g2 = _b2b_grid(p("liuyang"))
    assert all(row["values"].get("customer") != "Floor & Decor" for row in g2["rows"])
    assert "Floor & Decor" not in str(g2)
