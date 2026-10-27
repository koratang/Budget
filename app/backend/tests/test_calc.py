"""计算引擎纯函数（CMP-F06-01）。期望值全部取自 output/tests/TDD验收契约.md 对应行的文本，不由实现生成。"""
from datetime import date
from decimal import Decimal as D

from app.calc import formulas as f
from app.core.money import fmt_amount, fmt_percent, fmt_pp, round2

USD_BUDGET = D("7.12")


def money(x) -> str:
    return fmt_amount(x)


# ---- FLOW-11：Amazon-US-01 · 美国 · 浴室柜 · 新品 · 2027-03 ----
FLOW11_DRIVERS = f.PlatformDrivers(spu_count=10, avg_sales=D("120"), avg_price=D("80.00"), discount_rate=D("0.10"),
                                   refund_rate=D("0.05"), ad_rate=D("0.12"), commission_rate=D("0.15"))
FLOW11_COST = f.CostRates(purchase_cost_rate=D("0.30"), first_leg_rate=D("0.06"), last_mile_rate=D("0.08"),
                          storage_rate=D("0.02"), tariff_rate=D("0.04"))


def test_flow11_platform_unit():
    r = f.calc_platform_unit(FLOW11_DRIVERS, FLOW11_COST, D("0.01"), D("0.03"), USD_BUDGET)
    assert money(r.sales_qty) == "1,200.00"
    assert money(r.revenue_local) == "86,400.00"
    ln = r.lines
    expected = {
        "revenue_cny": "615,168.00", "refund": "30,758.40", "purchase_cost": "184,550.40",
        "commission": "92,275.20", "promotion": "73,820.16", "first_leg": "36,910.08", "last_mile": "49,213.44",
        "tariff": "24,606.72", "storage": "12,303.36", "inventory_claim": "6,151.68", "other_opex": "18,455.04",
        "gross_profit": "98,426.88",
    }
    assert {k: money(getattr(ln, k)) for k in expected} == expected
    assert fmt_percent(ln.gross_margin) == "16.00%"


def test_flow11_zero_revenue_margin_is_dash():
    zero = f.PlatformDrivers(0, D(0), D(0), D(0), D(0), D(0), D(0))
    r = f.calc_platform_unit(zero, FLOW11_COST, D(0), D(0), USD_BUDGET)
    assert r.lines.gross_margin is None and fmt_percent(r.lines.gross_margin) == "—"


def test_missing_budget_fx_leaves_cny_empty():
    r = f.calc_platform_unit(FLOW11_DRIVERS, FLOW11_COST, D(0), D(0), None)
    assert money(r.revenue_local) == "86,400.00" and r.lines is None


# ---- FLOW-12：Ferguson 2027-03 ----
def test_flow12_b2b_unit():
    ln = f.calc_b2b_unit(
        D("200000.00"),
        f.OpexRates(refund_rate=D("0.02"), promotion_rate=D("0.03"), other_opex_rate=D("0.01")),
        f.CostRates(purchase_cost_rate=D("0.55"), first_leg_rate=D("0.05"), last_mile_rate=D("0.02"),
                    storage_rate=D("0.01"), tariff_rate=D("0.07")),
        USD_BUDGET)
    expected = {
        "revenue_cny": "1,424,000.00", "refund": "28,480.00", "promotion": "42,720.00", "other_opex": "14,240.00",
        "purchase_cost": "783,200.00", "first_leg": "71,200.00", "last_mile": "28,480.00", "storage": "14,240.00",
        "tariff": "99,680.00", "commission": "0.00", "inventory_claim": "0.00", "gross_profit": "341,760.00",
    }
    assert {k: money(getattr(ln, k)) for k in expected} == expected
    assert fmt_percent(ln.gross_margin) == "24.00%"


# ---- FLOW-13：2027-03 公司净利润 ----
def test_flow13_company_net_profit():
    other_pl = D("-5000.00") + D("2000.00") + D("0.00") + D("-30000.00")
    assert other_pl == D("-33000.00")
    net = f.company_net_profit(D("98426.88"), D("341760.00"), D("300000.00"), other_pl)
    assert money(net) == "107,186.88"


# ---- FLOW-24：BI 与金蝶核对（USD 当月平均汇率 7.2000） ----
def test_flow24_reconciliation():
    amazon = f.reconcile(D("77000.00"), D("7.2000"), D("535000.00"))
    assert money(amazon.bi_cny) == "554,400.00"
    assert fmt_percent(amazon.diff_rate, signed=True) == "+3.63%" and amazon.flagged
    wayfair = f.reconcile(D("50000.00"), D("7.2000"), D("355000.00"))
    assert money(wayfair.bi_cny) == "360,000.00"
    assert fmt_percent(wayfair.diff_rate, signed=True) == "+1.41%" and not wayfair.flagged
    gbp = f.reconcile(D("10000.00"), None, D("90000.00"))
    assert gbp.missing_fx and gbp.bi_cny is None and not gbp.flagged
    assert [r for r in (amazon, wayfair, gbp) if r.flagged] == [amazon]


def test_reconciliation_zero_kingdee_revenue_rate_is_dash():
    r = f.reconcile(D("100"), D("7.2"), D("0"))
    assert r.diff_rate is None and fmt_percent(r.diff_rate) == "—"


# ---- FLOW-25：Amazon-US-01 2027-04 收入拆分与费率差 ----
def test_flow25_revenue_split():
    s = f.revenue_variance_split(budget_qty=D("1200"), budget_avg_price=D("80.00"), budget_discount_rate=D("0.10"),
                                 budget_fx=USD_BUDGET, actual_qty=D("1100"), actual_revenue_local=D("77000.00"),
                                 actual_fx=D("7.2000"), kingdee_revenue_cny=D("554400.00"))
    assert money(s.budget_revenue) == "615,168.00"
    assert money(s.total_variance) == "−60,768.00"
    assert fmt_percent(f.safe_ratio(s.actual_revenue, s.budget_revenue)) == "90.12%"
    assert money(s.volume) == "−51,264.00"
    assert money(s.price) == "−15,664.00"
    assert money(s.fx) == "6,160.00"
    assert money(s.basis) == "0.00"
    assert s.volume + s.price + s.fx + s.basis == s.total_variance


def test_flow25_split_without_actual_fx():
    s = f.revenue_variance_split(budget_qty=D("1200"), budget_avg_price=D("80"), budget_discount_rate=D("0.1"),
                                 budget_fx=USD_BUDGET, actual_qty=D("1100"), actual_revenue_local=D("77000"),
                                 actual_fx=None, kingdee_revenue_cny=D("554400"))
    assert s.missing_fx and s.fx is None and s.basis is None


def test_flow25_rate_variance_promotion():
    assert money(f.rate_variance(D("73000.00"), D("554400.00"), D("0.12"))) == "6,472.00"
    assert f.rate_variance(D("100"), D("0"), D("0.12")) is None


# ---- FLOW-26：品类报告品效、部门费用额度使用率与时间进度 ----
def test_flow26_product_efficiency():
    net = f.net_price(D("80.00"), D("0.10"))
    budget = f.budget_efficiency_cny([(10, D("1200"), net, USD_BUDGET)])
    actual = f.actual_efficiency_cny([(9, D("77000.00"), D("7.2000"))])
    assert money(budget) == "61,516.80"
    assert money(actual) == "61,600.00"
    assert money(actual - budget) == "83.20"
    # 单元级本币口径：120 × 72.00
    assert money(f.budget_efficiency_local(D("120"), D("80.00"), D("0.10"))) == "8,640.00"
    assert f.actual_efficiency_local(D("77000"), 0) is None
    assert f.budget_efficiency_cny([]) is None


def test_flow26_quota_usage_and_time_progress():
    assert fmt_percent(f.quota_usage(D("500000.00"), D("1200000.00"))) == "41.67%"
    assert fmt_percent(f.time_progress(4)) == "33.33%"
    assert f.quota_usage(D("1"), D("0")) is None


# ---- FLOW-27：净利润达成率双口径、增速、季度预测偏差 ----
def test_flow27_net_profit_achievement():
    assert fmt_percent(f.net_profit_achievement(D("3600000.00"), D("4000000.00")), places=1) == "90.0%"
    assert fmt_percent(f.net_profit_achievement(D("3600000.00"), D("3750000.00")), places=1) == "96.0%"
    assert f.net_profit_achievement(D("3600000.00"), D("-50000.00")) is None
    assert f.net_profit_achievement(D("1"), D("0")) is None


def test_flow27_growth():
    rev = f.growth_rate(D("112000000.00"), D("100000000.00"))
    exp = f.growth_rate(D("5800000.00"), D("5000000.00"))
    assert fmt_percent(rev, places=1, signed=True) == "+12.0%"
    assert fmt_percent(exp, places=1, signed=True) == "+16.0%"
    assert f.expense_growth_exceeds(exp, rev)
    assert f.growth_rate(D("1"), None) is None and not f.expense_growth_exceeds(None, rev)


def test_flow27_forecast_deviation():
    apr = f.forecast_deviation_pp(f.net_margin(D("500000.00"), D("10000000.00")),
                                  f.net_margin(D("320000.00"), D("9600000.00")))
    assert fmt_pp(apr) == "1.67" and f.forecast_deviation_alert(apr)
    mar = f.forecast_deviation_pp(D("0.0500"), D("0.0420"))
    assert fmt_pp(mar) == "0.80" and not f.forecast_deviation_alert(mar)


# ---- FLOW-05：新老品判定 ----
def test_flow05_new_product():
    fm2416 = date(2026, 3, 15)
    mc3026 = date(2026, 3, 31)
    assert f.is_new_product(date(2027, 2, 1), fm2416) is True
    assert f.is_new_product(date(2027, 3, 1), fm2416) is False
    assert f.is_new_product(date(2027, 3, 1), mc3026) is False


# ---- FLOW-04 / FLOW-17：新渠道期与放量上限 ----
def test_flow04_new_channel_period():
    start = date(2027, 3, 1)
    assert f.is_new_channel_period(date(2027, 3, 1), start)
    assert f.is_new_channel_period(date(2028, 2, 1), start)
    assert not f.is_new_channel_period(date(2028, 3, 1), start)
    assert not f.is_new_channel_period(date(2027, 2, 1), start)
    assert not f.is_new_channel_period(date(2027, 3, 1), None)


def test_flow17_ramp_limit():
    start = date(2027, 3, 1)
    limits = [D("200000.00"), D("300000.00")] + [D("400000.00")] * 10
    assert f.exceeds_ramp_limit(D("350000.00"), date(2027, 4, 1), start, limits) is True
    assert f.exceeds_ramp_limit(D("180000.00"), date(2027, 3, 1), start, limits) is False
    assert f.exceeds_ramp_limit(D("999999"), date(2027, 4, 1), start, None) is False  # 无生效规则不标注


# ---- FLOW-16：部门费用历史参考 ----
def test_flow16_history_reference():
    imported = [date(2025, 12, 1)] + [date(2026, m, 1) for m in range(1, 12)]
    training = {date(2025, 12, 1): D("30000.00"), date(2026, 4, 1): D("35000.00")}
    # 2026-01～11 合计 390,000.00（其中 2026-04 为 35,000.00）：其余 10 个月共 355,000.00
    for m in (1, 2, 3, 5, 6, 7, 8, 9, 10, 11):
        training[date(2026, m, 1)] = D("35500.00")
    assert money(sum(v for k, v in training.items() if k.year == 2026)) == "390,000.00"
    assert money(f.prior_year_same_month(training, date(2027, 4, 1))) == "35,000.00"
    assert money(f.recent_12_months_total(training, imported)) == "420,000.00"
    assert f.recent_12_months_total({}, imported) is None  # 员工关怀费：无历史数据
    assert f.prior_year_same_month({}, date(2027, 4, 1)) is None


# ---- RULE-01：金额精度 ----
def test_rule01_rounding():
    parts = [D("0.334")] * 3
    assert [money(p) for p in parts] == ["0.33", "0.33", "0.33"]
    total = sum(parts)
    assert money(total) == "1.00"
    assert abs(round2(total) - sum(round2(p) for p in parts)) <= D("0.01") * 3
    assert money(D("1.005")) == "1.01"
