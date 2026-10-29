"""FLOW-26 品类×新老品偏差（品效按人民币汇总，DEC-025）；部门费用报告已删除，仅断言其接口 404。

期望值逐字取自 TDD验收契约.md FLOW-26 行。
"""
from decimal import Decimal

from app.calc import formulas as F
from app.core.money import fmt_amount, round_to
from app.models.enums import VersionType

from tests.g4 import builders as B


def money(v):
    return fmt_amount(Decimal(v))


def integer(v):
    q = round_to(Decimal(v), 0)
    return f"{'−' if q < 0 else ''}{abs(q):,}"


def build_category(db):
    """只有 Amazon-US-01（USD）一个店铺：浴室柜 · 新品预算 SPU 10、销量 1,200、平均单价 80.00、折扣率 10%、
    预算汇率 7.12；BI 实际 SPU 9、销量 1,100、销售额 USD 77,000.00、当月平均汇率 7.2000。"""
    v = B.version(db, 2027, VersionType.ORIGINAL_TARGET, "V1 年初原始目标")
    B.platform_unit(db, v, "Amazon-US-01", "2027-04", "浴室柜", True, spu=10, avg_sales="120", avg_price="80.00",
                    discount="0.10")
    B.fx_actual(db, "2027-04", "USD", "7.2000")
    bi = B.batch(db, "bi", "2027-04", "BI_2027-03_04.xlsx")
    B.bi_agg(db, bi, "2027-04", "Amazon-US-01", "浴室柜", True, spu=9, qty="1100", revenue_local="77000.00",
             revenue_cny="554400.00")
    kd = B.batch(db, "kingdee", "2027-05")
    B.kingdee(db, kd, "2027-05", "平台销售收入", "500000.00", store_name="Amazon-US-01")


def test_efficiency_formulas_unit():
    b = F.budget_efficiency_cny([(10, Decimal("1200"), F.net_price(Decimal("80.00"), Decimal("0.10")),
                                  Decimal("7.12"))])
    a = F.actual_efficiency_cny([(9, Decimal("77000.00"), Decimal("7.2000"))])
    assert fmt_amount(b) == "61,516.80"
    assert fmt_amount(a) == "61,600.00"
    assert fmt_amount(a - b) == "83.20"


def test_category_report(client, seeded):
    db = seeded
    build_category(db)
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


def test_dept_report_removed(client, seeded):
    """部门费用报告已删除（2026-10-29）：接口不存在，返回 404。"""
    db = seeded
    B.login(client, db, "linxiao")
    assert client.get("/api/reports/dept-expense", params={"year": 2027}).status_code == 404
    B.login(client, db, "wujing")
    assert client.get("/api/reports/dept-expense", params={"year": 2027}).status_code == 404
