"""工作台（API-F00-01，PAGE-F00-01 §11）：待填报、未处理预警按范围、提交率、财务BP 导入卡片。"""
from datetime import date

from app.models import Alert, BudgetTask, FillingUnit, Rule, RuleVersion
from app.models.enums import UnitStatus, UnitType, VersionType

from tests.g4 import builders as B
from tests.g4.scenarios import flow25


def make_task(db, v):
    task = BudgetTask(name="2027 年度预算编制", year=2027, deadline=date(2026, 12, 20), version_id=v.id)
    db.add(task)
    db.flush()
    return task


def test_submit_rate_and_filling_todo(client, seeded):
    """24 个单位：6 已提交、3 已通过、2 已退回、其余未开始或填报中 → 提交率 37.5%。"""
    db = seeded
    v = B.version(db, 2027, VersionType.DRAFT, "2027 编制稿")
    task = make_task(db, v)
    statuses = ([UnitStatus.SUBMITTED] * 6 + [UnitStatus.APPROVED] * 3 + [UnitStatus.RETURNED] * 2
                + [UnitStatus.NOT_STARTED] * 7 + [UnitStatus.FILLING] * 6)
    wanghao, reviewer = B.user_id(db, "wanghao"), B.user_id(db, "zhaolei")
    for i, st in enumerate(statuses):
        db.add(FillingUnit(task_id=task.id, version_id=v.id, unit_type=UnitType.DEPT_EXPENSE, scope_object_id=i + 1,
                           name=f"单位{i + 1}", filler_id=wanghao if i == 9 else reviewer, reviewer_id=reviewer,
                           status=st, return_reason="驱动值偏高" if st == UnitStatus.RETURNED else None))
    db.flush()
    B.login(client, db, "linxiao")
    sub = client.get("/api/workbench").json()["key_metrics"]["submit"]
    assert (sub["submitted"], sub["total"], sub["rate"]) == (9, 24, "37.5")
    assert sub["in_progress"] is True

    B.login(client, db, "wanghao")
    wb = client.get("/api/workbench").json()
    filling = wb["todo"]["filling"]
    assert filling["count"] == 1
    item = filling["items"][0]
    assert item["status_label"] == "已退回" and item["return_reason"] == "驱动值偏高"
    assert item["link"].startswith("/dept-expense?unitId=")
    assert wb["todo"]["approvals"]["count"] == 0  # 运营没有待审批事项


def test_alerts_scoped_and_finance_bp_imports(client, seeded):
    db = seeded
    flow25(db)
    rule = Rule(name="新渠道连续 2 个月达成率低于 70%", type="alert_rule")
    db.add(rule)
    db.flush()
    rv = RuleVersion(rule_id=rule.id, version_no=2, content={"kind": "alert"}, credibility="unverified",
                     status="effective")
    db.add(rv)
    db.flush()
    us, ca = B.store(db, "Amazon-US-01"), B.store(db, "Amazon-CA-01")
    db.add_all([Alert(rule_version_id=rv.id, object_type="store", object_id=str(us.id), object_name="Amazon-US-01",
                      period=date(2027, 4, 1)),
                Alert(rule_version_id=rv.id, object_type="store", object_id=str(ca.id), object_name="Amazon-CA-01",
                      period=date(2027, 4, 1))])
    db.flush()
    B.login(client, db, "wanghao")
    alerts = client.get("/api/workbench").json()["todo"]["alerts"]
    assert alerts["count"] == 1
    assert alerts["items"][0]["object_name"] == "Amazon-US-01"
    assert alerts["items"][0]["rule_version"] == "v2"
    B.login(client, db, "linxiao")
    assert client.get("/api/workbench").json()["todo"]["alerts"]["count"] == 2

    B.login(client, db, "chensiyu")
    wb = client.get("/api/workbench").json()
    assert wb["key_metrics"] is None
    imp = wb["imports"]
    assert imp["kingdee_latest"] == "2027-05" and imp["bi_latest"] == "2027-04"
    # 2027-04：Amazon-US-01 BI 折人民币 554,400.00 = 金蝶；Amazon-CA-01 BI 25,000 × 5.2410 = 131,025 与金蝶 130,000
    # 差异 0.79%，均未超 3%
    assert imp["reconcile"] == {"month": "2027-04", "count": 0}
