"""FLOW-27 公司汇总与工作台：净利润达成率双口径、增速对比、季度预测准确度。

期望值逐字取自 TDD验收契约.md FLOW-27 行：
1–4 月实际净利润合计 3,600,000.00，原始目标同期 4,000,000.00，调整后目标同期 3,750,000.00；
2027-01～04 部门费用 5,800,000.00、收入 112,000,000.00，2026-01～04 分别 5,000,000.00 与 100,000,000.00；
2027-04 Q2 快照预测净利润 500,000.00、收入 10,000,000.00，实际净利润 320,000.00、收入 9,600,000.00；
2027-03 Q1 快照预测净利润率 5.00%，实际 4.20%；另造一年度同期目标合计为 −50,000.00。
"""
from datetime import date
from decimal import Decimal

from app.core.money import round_to
from app.models.enums import VersionType

from tests.g4 import builders as B


def pct1(v):
    return "—" if v is None else f"{round_to(Decimal(v), 1)}%"


def signed1(v):
    q = round_to(Decimal(v), 1)
    return f"{'+' if q > 0 else ''}{q}%"


def pp2(v):
    return f"{round_to(Decimal(v), 2)}"


# 每月：(人民币收入, 部门费用, 实际净利润)；采购成本 = 收入 − 部门费用 − 净利润
ACTUAL_2027 = {1: ("36200000.00", "1500000.00", "1010000.00"), 2: ("36200000.00", "1500000.00", "1010000.00"),
               3: ("30000000.00", "1350000.00", "1260000.00"), 4: ("9600000.00", "1450000.00", "320000.00")}
ACTUAL_2026 = {m: ("25000000.00", "1250000.00", "0.00") for m in range(1, 5)}


def import_month(db, year, month, revenue, dept_exp, net_profit, source="kingdee"):
    ym = f"{year}-{month:02d}"
    b = B.batch(db, source, ym)
    purchase = Decimal(revenue) - Decimal(dept_exp) - Decimal(net_profit)
    B.kingdee(db, b, ym, "平台销售收入", revenue, store_name="Amazon-US-01")
    B.kingdee(db, b, ym, "采购成本", str(purchase), store_name="Amazon-US-01")
    B.kingdee(db, b, ym, "工资薪酬", dept_exp, dept_name="人力资源部")


def build(db):
    orig = B.version(db, 2027, VersionType.ORIGINAL_TARGET, "V1 年初原始目标")
    adj = B.version(db, 2027, VersionType.ADJUSTED_TARGET, "V2 2027Q2 目标调整", version_no=2)
    for m in range(1, 5):
        B.raw_platform_unit(db, orig, "Amazon-US-01", f"2027-{m:02d}", revenue_cny="20000000.00",
                            gross_profit="1000000.00")
        B.raw_platform_unit(db, adj, "Amazon-US-01", f"2027-{m:02d}", revenue_cny="20000000.00",
                            gross_profit="750000.00" if m == 4 else "1000000.00")
    for m, vals in ACTUAL_2027.items():
        import_month(db, 2027, m, *vals)
    for m, vals in ACTUAL_2026.items():
        import_month(db, 2026, m, *vals, source="kingdee-history")
    q1 = B.version(db, 2027, VersionType.SNAPSHOT, "Q1 快照（以年初原始目标发布）", quarter=1,
                   published_on=date(2027, 1, 4))
    for m in (1, 2, 3):
        B.snapshot_month(db, q1, f"2027-{m:02d}", revenue="10000000.00", net_profit="500000.00")
    q2 = B.version(db, 2027, VersionType.SNAPSHOT, "2027Q2 滚动预测快照", version_no=2, quarter=2, published_on=date(2027, 4, 10))
    for m in (4, 5, 6):
        B.snapshot_month(db, q2, f"2027-{m:02d}", revenue="10000000.00", net_profit="500000.00")


def test_company_summary(client, seeded):
    db = seeded
    build(db)
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
    build(db)
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
    build(db)
    v = B.version(db, 2028, VersionType.ORIGINAL_TARGET, "V1 2028 年初原始目标")
    for m, gp in ((1, "-30000.00"), (2, "-20000.00"), (3, "0.00"), (4, "0.00"), (5, "0.00")):
        B.raw_platform_unit(db, v, "Amazon-US-01", f"2028-{m:02d}", revenue_cny="1000000.00", gross_profit=gp)
    for m in range(1, 6):
        import_month(db, 2028, m, "1000000.00", "100000.00", "10000.00")
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
    build(db)
    B.login(client, db, "wanghao")
    r = client.get("/api/reports/company", params={"year": 2027})
    assert r.status_code == 403 and r.json() == {"code": "forbidden", "message": "无权限"}
