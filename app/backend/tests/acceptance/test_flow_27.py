"""FLOW-27 验收（真实路由 + 权限 + 数据库）：公司汇总与工作台：净利润达成率双口径、增速对比、季度预测准确度。

期望值逐字取自 TDD验收契约.md FLOW-27 行：
1–4 月实际净利润合计 3,600,000.00，原始目标同期 4,000,000.00，调整后目标同期 3,750,000.00；
2027-01～04 部门费用 5,800,000.00、收入 112,000,000.00，2026-01～04 分别 5,000,000.00 与 100,000,000.00；
2027-04 Q2 快照预测净利润 500,000.00、收入 10,000,000.00，实际净利润 320,000.00、收入 9,600,000.00；
2027-03 Q1 快照预测净利润率 5.00%，实际 4.20%；另造一年度同期目标合计为 −50,000.00。
"""
from decimal import Decimal

from app.core.money import round_to

from tests.acceptance.e3_scenarios import flow27, flow27_2028
from tests.g4 import builders as B


def pct1(v):
    return "—" if v is None else f"{round_to(Decimal(v), 1)}%"


def signed1(v):
    q = round_to(Decimal(v), 1)
    return f"{'+' if q > 0 else ''}{q}%"


def pp2(v):
    return f"{round_to(Decimal(v), 2)}"


def test_company_summary(client, seeded):
    db = seeded
    flow27(db)
    B.login(client, db, "linxiao")
    data = client.get("/api/reports/company", params={"year": 2027}).json()
    ach = data["achievement"]
    assert data["through"] == "2027-04"
    assert Decimal(ach["actual_sum"]) == Decimal("3600000.00")
    assert pct1(ach["original"]["rate"]) == "90.0%"
    assert pct1(ach["adjusted"]["rate"]) == "96.0%"
    g = data["growth"]
    assert signed1(g["revenue"]["growth"]) == "+12.0%"
    assert signed1(g["dept_expense"]["growth"]) == "+16.0%"
    assert g["expense_faster"] is True
    acc = {a["month"]: a for a in data["accuracy"]}
    apr = acc["2027-04"]
    assert f"{round_to(Decimal(apr['forecast_margin']), 2)}" == "5.00"
    assert f"{round_to(Decimal(apr['actual_margin']), 2)}" == "3.33"
    assert pp2(apr["deviation_pp"]) == "1.67" and apr["flagged"] is True
    assert pp2(acc["2027-03"]["deviation_pp"]) == "0.80" and acc["2027-03"]["flagged"] is False
    assert acc["2027-05"]["actual_imported"] is False


def test_workbench_shows_same_rates(client, seeded):
    db = seeded
    flow27(db)
    B.login(client, db, "linxiao")
    wb = client.get("/api/workbench").json()
    ach = wb["key_metrics"]["achievement"]
    assert pct1(ach["original"]["rate"]) == "90.0%"
    assert pct1(ach["adjusted"]["rate"]) == "96.0%"
    fc = wb["key_metrics"]["forecast"]
    assert fc["quarter"] == 2
    assert [(m["month"], pp2(m["deviation_pp"]), m["flagged"]) for m in fc["months"]] == [("2027-04", "1.67", True)]
    # 运营看不到关键数区
    B.login(client, db, "wanghao")
    assert client.get("/api/workbench").json()["key_metrics"] is None


def test_non_positive_target_and_missing_prior_year(client, seeded):
    """另造一年度（2028）同期目标合计 −50,000.00；该年度上年同期（2027-05）未导入时显示提示。"""
    db = seeded
    flow27(db)
    flow27_2028(db)
    B.login(client, db, "linxiao")
    data = client.get("/api/reports/company", params={"year": 2028}).json()
    ach = data["achievement"]
    assert Decimal(ach["original"]["target_sum"]) == Decimal("-50000.00")
    assert pct1(ach["original"]["rate"]) == "—"
    assert pct1(ach["adjusted"]["rate"]) == "—"
    assert data["growth"]["available"] is False
    assert data["growth"]["message"] == "上年同期实际未导入，暂不计算增速"
    # 2028 为最近导入年度：工作台同样显示「—」
    wb = client.get("/api/workbench").json()
    assert wb["key_metrics"]["achievement"]["original"]["rate"] is None


def test_company_summary_forbidden_for_operations(client, seeded):
    db = seeded
    flow27(db)
    B.login(client, db, "wanghao")
    r = client.get("/api/reports/company", params={"year": 2027})
    assert r.status_code == 403 and r.json() == {"code": "forbidden", "message": "无权限"}


def test_workbench_header_budget_year_during_compilation(client, seeded):
    """PAGE-F00-01 页头「预算年度」：编制期（2026-12，金蝶最近导入 2026-11）显示正在编制的年度 2027。"""
    from datetime import date

    from app.models import BudgetTask
    from app.models.enums import TaskStatus, VersionType

    db = seeded
    v = B.version(db, 2027, VersionType.DRAFT, "2027 编制稿")
    db.add(BudgetTask(name="2027 年度预算编制", year=2027, deadline=date(2026, 12, 20), version_id=v.id,
                      status=TaskStatus.IN_PROGRESS))
    kd = B.batch(db, "kingdee", "2026-11")
    B.kingdee(db, kd, "2026-11", "平台销售收入", "100000.00", store_name="Amazon-US-01")
    B.login(client, db, "linxiao")
    wb = client.get("/api/workbench").json()
    assert wb["budget_year"] == 2027
    assert wb["kingdee_latest"] == "2026-11"
