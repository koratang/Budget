"""FLOW-26 验收（真实路由 + 权限 + 数据库）：品类×新老品偏差（品效按人民币汇总，DEC-025）与部门费用报告（额度使用率、时间进度）。

期望值逐字取自 TDD验收契约.md FLOW-26 行。
"""
from decimal import Decimal

from app.calc import formulas as F
from app.core.money import fmt_amount, round_to

from tests.acceptance.e3_scenarios import flow26_category, flow26_dept
from tests.g4 import builders as B


def money(v):
    return fmt_amount(Decimal(v))


def integer(v):
    q = round_to(Decimal(v), 0)
    return f"{'−' if q < 0 else ''}{abs(q):,}"


def rate2(v):
    return f"{round_to(Decimal(v), 2)}%"


def test_efficiency_formulas_unit():
    b = F.budget_efficiency_cny([(10, Decimal("1200"), F.net_price(Decimal("80.00"), Decimal("0.10")),
                                  Decimal("7.12"))])
    a = F.actual_efficiency_cny([(9, Decimal("77000.00"), Decimal("7.2000"))])
    assert fmt_amount(b) == "61,516.80"
    assert fmt_amount(a) == "61,600.00"
    assert fmt_amount(a - b) == "83.20"


def test_category_report(client, seeded):
    db = seeded
    flow26_category(db)
    B.login(client, db, "linxiao")
    data = client.get("/api/reports/category").json()
    # 月份下拉只列有 BI 实际的月份（2027-05 只有金蝶，不列入）
    assert data["months"] == ["2027-04"]
    assert data["month"] == "2027-04"
    group = next(g for g in data["groups"] if g["category"] == "浴室柜")
    row = next(r for r in group["rows"] if r["kind"] == "新品")
    assert (row["spu"]["budget"], row["spu"]["actual"], row["spu"]["diff"]) == ("10", "9", "-1")
    assert [integer(row["qty"][k]) for k in ("budget", "actual", "diff")] == ["1,200", "1,100", "−100"]
    assert [money(row["efficiency"][k]) for k in ("budget", "actual", "diff")] == ["61,516.80", "61,600.00",
                                                                                   "83.20"]
    assert [money(row["revenue"][k]) for k in ("budget", "actual", "diff")] == ["615,168.00", "554,400.00",
                                                                                "−60,768.00"]
    # 选择没有 BI 实际的月份：空态提示
    empty = client.get("/api/reports/category", params={"month": "2027-05"}).json()
    assert empty["empty"] is True


def test_dept_report(client, seeded):
    """人力资源部培训费全年预算 1,200,000.00、2027-01 至 2027-04 累计实际 500,000.00。"""
    db = seeded
    flow26_dept(db)
    B.login(client, db, "linxiao")
    data = client.get("/api/reports/dept-expense", params={"year": 2027}).json()
    group = next(g for g in data["groups"] if g["department"] == "人力资源部")
    row = next(r for r in group["rows"] if r["account"] == "培训费")
    assert money(row["budget"]) == "1,200,000.00"
    assert money(row["actual"]) == "500,000.00"
    assert rate2(row["usage"]) == "41.67%"
    assert rate2(data["time_progress"]) == "33.33%"
    assert data["imported_months"] == 4
    # 部门负责人只看到本部门；无部门范围的角色 403
    B.login(client, db, "wujing")
    mine = client.get("/api/reports/dept-expense", params={"year": 2027}).json()
    assert [g["department"] for g in mine["groups"]] == ["人力资源部"]
    assert mine["total"]["department"] == "合计（我的部门）"
    B.login(client, db, "wanghao")
    assert client.get("/api/reports/dept-expense", params={"year": 2027}).status_code == 403
