"""FLOW-08 新增 B 端客户（REQ-F02-05，AC-F02-09）：期望值逐字取自 TDD验收契约 FLOW-08。

B 端填报表格（API-F04-02，G2）按主数据服务 b2b_customers_for_department 列出负责部门的客户；
「客户组 6 个输入项」由 G2 的填报表格测试覆盖。
"""
from sqlalchemy import func, select

from app.models import BCustomer
from app.services.masterdata import b2b_customers_for_department
from tests.g1.helpers import dept_id, login


def test_new_customer_listed_for_its_department_only(seeded, db, dingtalk):
    bp = login(db, dingtalk, "chensiyu")
    us_dept, trade = dept_id(db, "美国业务部"), dept_id(db, "外贸部")
    r = bp.post("/api/master/b-customers", json={"name": "Floor & Decor", "department_id": us_dept, "currency": "USD"})
    assert r.status_code == 201, r.text
    assert [c.name for c in b2b_customers_for_department(db, us_dept)] == ["Ferguson", "Menards", "Floor & Decor"]
    assert "Floor & Decor" not in [c.name for c in b2b_customers_for_department(db, trade)]
    page = bp.get("/api/master/b-customers").json()
    row = next(i for i in page["items"] if i["name"] == "Floor & Decor")
    assert (row["department_name"], row["currency"]) == ("美国业务部", "USD")

    count = db.scalar(select(func.count()).select_from(BCustomer))
    r = bp.post("/api/master/b-customers", json={"name": "Floor & Decor", "department_id": trade, "currency": "EUR"})
    assert r.status_code == 422 and r.json()["message"] == "客户名称不能重复"
    assert db.scalar(select(func.count()).select_from(BCustomer)) == count


def test_customer_department_limited_and_readonly_roles(seeded, db, dingtalk):
    bp = login(db, dingtalk, "chensiyu")
    r = bp.post("/api/master/b-customers", json={"name": "Home Hardware", "department_id": dept_id(db, "市场部"),
                                                 "currency": "CAD"})
    assert r.status_code == 422 and r.json()["message"] == "负责部门只能是美国业务部或外贸部"
    head = login(db, dingtalk, "linxiao")
    assert head.get("/api/master/b-customers").json()["can_edit"] is False
    assert head.post("/api/master/b-customers", json={"name": "Home Hardware", "department_id": dept_id(
        db, "美国业务部"), "currency": "CAD"}).status_code == 403
    assert login(db, dingtalk, "sunting").get("/api/master/b-customers").status_code == 403
