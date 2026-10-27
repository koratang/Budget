"""FLOW-06 验收（API 层，真实路由 + 数据库）：期望值逐字取自 TDD验收契约 FLOW-06。

陈思雨把金蝶科目「6601.12 广告宣传费」映射到预算科目「市场推广费」，随后导入含 6601.12 发生额 38,000.00 的 2027-04 金蝶文件
→ 市场部 2027-04「市场推广费」实际增加 38,000.00；在预算科目页新增「员工关怀费」、把「差旅费」改名为「差旅交通费」、停用「招待费」
→ 部门费用填报与科目映射下拉出现「员工关怀费」「差旅交通费」，不再出现「差旅费」「招待费」；「招待费」已有预算与实际在部门费用报告中仍显示。
"""
from decimal import Decimal

from sqlalchemy import select

from app.models import BudgetAccount
from tests.acceptance.e1_helpers import DEADLINE, KINGDEE_HEADER, XLSX, People, flow06_setup, xlsx


def _acc(db, name):
    return db.scalar(select(BudgetAccount.id).where(BudgetAccount.name == name))


def _dept_row(c, account):
    d = c.get("/api/reports/dept-expense", params={"year": 2027}).json()
    g = next(g for g in d["groups"] if g["department"] == "市场部")
    return next((r for r in g["rows"] if r["account"] == account), None), d


def test_flow_06(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    flow06_setup(db, p)
    bp, lin = p("chensiyu"), p("linxiao")

    r = bp.post("/api/master/account-mapping", json={"kingdee_code": "6601.12", "kingdee_name": "广告宣传费",
                                                     "account_id": _acc(db, "市场推广费")})
    assert r.status_code == 201, r.text
    before, _ = _dept_row(lin, "市场推广费")
    before_actual = Decimal(before["actual"])
    r = bp.post("/api/imports", files={"file": ("金蝶_2027-04_利润表.xlsx", xlsx(KINGDEE_HEADER, [
        ["2027-04", "6601.12", "广告宣传费", "市场部", "", "", "", "", 38000.00]]), XLSX)}, data={"source": "kingdee"})
    batch = bp.get(f"/api/imports/{r.json()['id']}").json()
    assert batch["status"] == "passed" and batch["issues"] == [], batch
    assert bp.post(f"/api/imports/{batch['id']}/confirm", json={"overwrite": False}).status_code == 200
    after, rep = _dept_row(lin, "市场推广费")
    assert rep["through"] == "2027-04"
    assert Decimal(after["actual"]) - before_actual == Decimal("38000.00")

    assert bp.post("/api/master/budget-accounts", json={"name": "员工关怀费"}).status_code == 201
    assert bp.put(f"/api/master/budget-accounts/{_acc(db, '差旅费')}", json={"name": "差旅交通费"}).status_code == 200
    assert bp.put(f"/api/master/budget-accounts/{_acc(db, '招待费')}", json={"status": "停用"}).status_code == 200

    mapping = [a["name"] for a in bp.get("/api/master/account-mapping").json()["account_options"]]
    assert "员工关怀费" in mapping and "差旅交通费" in mapping
    assert "差旅费" not in mapping and "招待费" not in mapping

    # 新填报：发布含市场部的编制任务，部门费用填报的科目行
    cands = lin.get("/api/tasks/candidates").json()["items"]
    units = [{"unit_type": c["unit_type"], "scope_object_id": c["scope_object_id"]} for c in cands
             if c["name"] == "市场部" and c["unit_type"] == "dept_expense"]
    r = lin.post("/api/tasks", json={"year": 2027, "deadline": DEADLINE, "units": units})
    assert r.status_code == 201, r.text
    dl = p("e1-denglin")
    unit_id = dl.get("/api/dept-expense/my-unit").json()["unit_id"]
    g = dl.get(f"/api/dept-expense/{unit_id}/grid").json()
    accounts = {row["values"].get("account") for row in g["rows"] if row.get("kind") == "input"}
    assert {"员工关怀费", "差旅交通费"} <= accounts, accounts
    assert not ({"差旅费", "招待费"} & accounts), accounts

    hosp, _ = _dept_row(lin, "招待费")
    assert hosp is not None
    assert Decimal(hosp["budget"]) == Decimal("12000") and Decimal(hosp["actual"]) == Decimal("5200")
