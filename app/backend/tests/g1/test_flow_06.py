"""FLOW-06 科目映射与预算科目清单（REQ-F02-03，AC-F02-05/12）：期望值逐字取自 TDD验收契约 FLOW-06。

金蝶导入入库（G3）按主数据服务 account_map_lookup 归集；本测试按该映射写入 2027-04 金蝶实际行验证归集口径，
部门费用报告（G4）对已停用科目照常显示由数据保留保证（本测试断言已有预算与实际行及科目名称保留）。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.models import (BudgetAccount, BudgetVersion, DeptExpense, ImportBatch, KingdeeAccountMap, KingdeeActual,
                        User)
from app.models.enums import ImportSource, ImportStatus, VersionType
from app.services.masterdata import account_map_lookup, dept_expense_accounts
from tests.g1.helpers import account_id, dept_id, login

APRIL = date(2027, 4, 1)


def _prepare(db):
    """前置主数据：预算科目清单含「市场推广费」「差旅费」「招待费」，尚无「员工关怀费」，6601.12 尚未映射。"""
    care = account_id(db, "员工关怀费")
    db.execute(delete(KingdeeAccountMap).where(KingdeeAccountMap.account_id == care))
    db.execute(delete(BudgetAccount).where(BudgetAccount.id == care))
    db.get(BudgetAccount, account_id(db, "业务招待费")).name = "招待费"
    db.add(BudgetAccount(name="市场推广费", is_dept_expense=True, sort=11))
    db.flush()
    uploader = db.scalar(select(User.id).where(User.dingtalk_userid == "chensiyu"))
    v = BudgetVersion(year=2027, type=VersionType.DRAFT, version_no=1, name="2027 编制稿")
    batch = ImportBatch(source=ImportSource.KINGDEE, period=APRIL, file_name="金蝶利润表_2027-04.xlsx",
                        status=ImportStatus.EFFECTIVE, uploaded_by=uploader)
    db.add_all([v, batch])
    db.flush()
    # 「招待费」已有预算与实际
    hosp = account_id(db, "招待费")
    db.add(DeptExpense(version_id=v.id, month=APRIL, department_id=dept_id(db, "市场部"), account_id=hosp,
                       amount=Decimal("6000")))
    db.add(KingdeeActual(batch_id=batch.id, month=APRIL, department_id=dept_id(db, "市场部"), kingdee_code="6602.10",
                         account_id=hosp, amount=Decimal("5200")))
    db.flush()
    return batch


def _market_actual(db):
    return db.scalar(select(func.coalesce(func.sum(KingdeeActual.amount), 0))
                     .where(KingdeeActual.month == APRIL, KingdeeActual.department_id == dept_id(db, "市场部"),
                            KingdeeActual.account_id == account_id(db, "市场推广费")))


def test_mapping_aggregates_following_imports(seeded, db, dingtalk):
    batch = _prepare(db)
    bp = login(db, dingtalk, "chensiyu")
    assert "6601.12" not in account_map_lookup(db)
    r = bp.post("/api/master/account-mapping", json={"kingdee_code": "6601.12", "kingdee_name": "广告宣传费",
                                                     "account_id": account_id(db, "市场推广费")})
    assert r.status_code == 201, r.text
    assert bp.post("/api/master/account-mapping", json={"kingdee_code": "6601.12", "account_id": account_id(
        db, "市场推广费")}).json()["message"] == "该金蝶科目编码已有映射，请在列表中修改"
    before = _market_actual(db)
    # 2027-04 金蝶文件中 6601.12 发生额 38,000.00，按映射归集
    db.add(KingdeeActual(batch_id=batch.id, month=APRIL, department_id=dept_id(db, "市场部"), kingdee_code="6601.12",
                         account_id=account_map_lookup(db)["6601.12"], amount=Decimal("38000.00")))
    db.flush()
    assert _market_actual(db) - before == Decimal("38000.00")
    listed = bp.get("/api/master/account-mapping").json()["items"]
    assert next(i for i in listed if i["kingdee_code"] == "6601.12")["account_name"] == "市场推广费"


def test_budget_account_list_changes(seeded, db, dingtalk):
    _prepare(db)
    bp = login(db, dingtalk, "chensiyu")
    r = bp.post("/api/master/budget-accounts", json={"name": "员工关怀费"})
    assert r.status_code == 201
    assert bp.post("/api/master/budget-accounts", json={"name": "员工关怀费"}).json()["message"] == "预算科目名称已存在"
    assert bp.put(f"/api/master/budget-accounts/{account_id(db, '差旅费')}", json={"name": "差旅交通费"}).status_code == 200
    hosp = account_id(db, "招待费")
    assert bp.put(f"/api/master/budget-accounts/{hosp}", json={"status": "停用"}).status_code == 200

    filling = [a["name"] for a in bp.get("/api/master/budget-accounts", params={"usage": "dept_expense"}).json()["items"]]
    mapping = [a["name"] for a in bp.get("/api/master/account-mapping").json()["account_options"]]
    for names in (filling, mapping, [a.name for a in dept_expense_accounts(db)]):
        assert "员工关怀费" in names and "差旅交通费" in names
        assert "差旅费" not in names and "招待费" not in names
    # 已停用科目的预算与实际保留
    assert db.scalar(select(DeptExpense.amount).where(DeptExpense.account_id == hosp)) == Decimal("6000")
    assert db.scalar(select(KingdeeActual.amount).where(KingdeeActual.account_id == hosp)) == Decimal("5200")
    assert db.get(BudgetAccount, hosp).name == "招待费"
