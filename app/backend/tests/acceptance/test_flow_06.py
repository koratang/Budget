"""FLOW-06 验收（API 层，真实路由 + 数据库）：期望值逐字取自 TDD验收契约 FLOW-06。

陈思雨把金蝶科目「6601.12 广告宣传费」映射到预算科目「市场推广费」，随后导入含 6601.12 发生额 38,000.00 的 2027-04 金蝶文件
→ 市场部 2027-04「市场推广费」实际增加 38,000.00；在预算科目页新增「员工关怀费」、把「差旅费」改名为「差旅交通费」、停用「招待费」
→ 部门费用填报与科目映射下拉出现「员工关怀费」「差旅交通费」，不再出现「差旅费」「招待费」；「招待费」已有预算与实际数据仍保留。
（部门费用报告已于 2026-10-29 删除，实际与预算改为直接核对生效数据。）
"""
from decimal import Decimal

from sqlalchemy import func, select

from app.models import BudgetAccount, BudgetVersion, Department, DeptExpense, ImportBatch, KingdeeActual
from app.models.enums import ImportStatus, VersionType
from tests.acceptance.e1_helpers import DEADLINE, KINGDEE_HEADER, XLSX, People, flow06_setup, xlsx


def _acc(db, name):
    return db.scalar(select(BudgetAccount.id).where(BudgetAccount.name == name))


def _mkt(db):
    return db.scalar(select(Department.id).where(Department.name == "市场部"))


def _actual(db, account):
    """市场部 2027 年该科目的生效金蝶实际合计。"""
    return db.scalar(select(func.coalesce(func.sum(KingdeeActual.amount), 0))
                     .join(ImportBatch, ImportBatch.id == KingdeeActual.batch_id)
                     .where(ImportBatch.status == ImportStatus.EFFECTIVE, KingdeeActual.department_id == _mkt(db),
                            KingdeeActual.account_id == _acc(db, account),
                            func.extract("year", KingdeeActual.month) == 2027))


def _budget(db, account):
    """市场部该科目在 2027 年初原始目标中的预算合计。"""
    return db.scalar(select(func.coalesce(func.sum(DeptExpense.amount), 0))
                     .join(BudgetVersion, BudgetVersion.id == DeptExpense.version_id)
                     .where(BudgetVersion.year == 2027, BudgetVersion.type == VersionType.ORIGINAL_TARGET,
                            DeptExpense.department_id == _mkt(db), DeptExpense.account_id == _acc(db, account)))


def test_flow_06(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    flow06_setup(db, p)
    bp, lin = p("chensiyu"), p("linxiao")

    r = bp.post("/api/master/account-mapping", json={"kingdee_code": "6601.12", "kingdee_name": "广告宣传费",
                                                     "account_id": _acc(db, "市场推广费")})
    assert r.status_code == 201, r.text
    before_actual = _actual(db, "市场推广费")
    r = bp.post("/api/imports", files={"file": ("金蝶_2027-04_利润表.xlsx", xlsx(KINGDEE_HEADER, [
        ["2027-04", "6601.12", "广告宣传费", "市场部", "", "", "", "", 38000.00]]), XLSX)}, data={"source": "kingdee"})
    batch = bp.get(f"/api/imports/{r.json()['id']}").json()
    assert batch["status"] == "passed" and batch["issues"] == [], batch
    assert bp.post(f"/api/imports/{batch['id']}/confirm", json={"overwrite": False}).status_code == 200
    assert _actual(db, "市场推广费") - before_actual == Decimal("38000.00")

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

    # 已停用的「招待费」：已有预算与实际保留
    assert _budget(db, "招待费") == Decimal("12000") and _actual(db, "招待费") == Decimal("5200")
    assert lin.get("/api/reports/dept-expense", params={"year": 2027}).status_code == 404
