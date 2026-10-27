"""计算引擎纯函数 CMP-F06-01（技术方案 §4.3）。

约定：
- 全部 Decimal，比率为小数（0.12 = 12%）；函数不舍入，舍入只在显示 / 导出（app.core.money）。
- 无法计算时返回 None（前端显示「—」），不抛错、不默认 0。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.calc.periods import add_months, month_end, month_start, months_between

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)

# AC-F10-10：季度预测偏差大于 1.5 个百分点标红；AC-F09-07：|差异率| > 3% 标红
FORECAST_DEVIATION_ALERT_PP = Decimal("1.5")
RECONCILE_ALERT_RATE = Decimal("0.03")


# ---------------------------------------------------------------------------
# 预算单元：收入 → 费用 → 毛利（AC-F06-01~05）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PlatformDrivers:
    """平台渠道七个驱动（运营）。"""
    spu_count: int
    avg_sales: Decimal
    avg_price: Decimal
    discount_rate: Decimal
    refund_rate: Decimal
    ad_rate: Decimal
    commission_rate: Decimal


@dataclass(frozen=True)
class CostRates:
    """成本类比率：采购成本占比（财务BP）与物流四项（物流物控）。平台渠道按月 × 渠道 × 站点 × 品类，B 端按月 × 客户。"""
    purchase_cost_rate: Decimal = ZERO
    first_leg_rate: Decimal = ZERO
    last_mile_rate: Decimal = ZERO
    storage_rate: Decimal = ZERO
    tariff_rate: Decimal = ZERO


@dataclass(frozen=True)
class OpexRates:
    """以人民币收入为基数的其余比率。平台渠道：退款/佣金/广告来自运营，库存索赔/其他运营来自渠道站点比例。"""
    refund_rate: Decimal = ZERO
    commission_rate: Decimal = ZERO
    promotion_rate: Decimal = ZERO
    inventory_claim_rate: Decimal = ZERO
    other_opex_rate: Decimal = ZERO


@dataclass(frozen=True)
class ProfitLines:
    """人民币收入及各项费用、毛利、毛利率（与 platform_unit / b2b_unit 派生列同名）。"""
    revenue_cny: Decimal
    refund: Decimal
    purchase_cost: Decimal
    commission: Decimal
    promotion: Decimal
    first_leg: Decimal
    last_mile: Decimal
    tariff: Decimal
    storage: Decimal
    inventory_claim: Decimal
    other_opex: Decimal
    gross_profit: Decimal
    gross_margin: Decimal | None


@dataclass(frozen=True)
class PlatformResult:
    sales_qty: Decimal
    revenue_local: Decimal
    lines: ProfitLines | None  # 缺预算汇率时为空


def sales_qty(spu_count: int, avg_sales: Decimal) -> Decimal:
    """AC-F06-01：销量 = SPU 数量 × 单 SPU 平均销量。"""
    return Decimal(spu_count) * avg_sales


def net_price(avg_price: Decimal, discount_rate: Decimal) -> Decimal:
    """净单价 = 平均单价 × (1 − 折扣率)。"""
    return avg_price * (ONE - discount_rate)


def revenue_local(qty: Decimal, avg_price: Decimal, discount_rate: Decimal) -> Decimal:
    """AC-F06-01：收入（本币）= 销量 × 平均单价 × (1 − 折扣率)。"""
    return qty * net_price(avg_price, discount_rate)


def revenue_cny(amount_local: Decimal, fx_rate: Decimal) -> Decimal:
    """AC-F06-02：人民币收入 = 收入（本币）× 该币种该预算年度的预算汇率。"""
    return amount_local * fx_rate


def gross_margin(gross_profit: Decimal, revenue: Decimal) -> Decimal | None:
    """AC-F06-04：毛利率 = 毛利 ÷ 人民币收入；收入为 0 时为空（显示「—」）。"""
    if revenue == 0:
        return None
    return gross_profit / revenue


def profit_lines(rev_cny: Decimal, cost: CostRates, opex: OpexRates) -> ProfitLines:
    """AC-F06-03/04：以人民币收入为基数乘各比率；
    毛利 = 收入 − 退款 − 采购成本 − 佣金 − 推广 − 头程 − 尾程 − 关税 − 仓储 + 库存索赔 − 其他运营费用。"""
    refund = rev_cny * opex.refund_rate
    purchase = rev_cny * cost.purchase_cost_rate
    commission = rev_cny * opex.commission_rate
    promotion = rev_cny * opex.promotion_rate
    first_leg = rev_cny * cost.first_leg_rate
    last_mile = rev_cny * cost.last_mile_rate
    tariff = rev_cny * cost.tariff_rate
    storage = rev_cny * cost.storage_rate
    claim = rev_cny * opex.inventory_claim_rate
    other = rev_cny * opex.other_opex_rate
    gp = (rev_cny - refund - purchase - commission - promotion - first_leg - last_mile - tariff - storage
          + claim - other)
    return ProfitLines(revenue_cny=rev_cny, refund=refund, purchase_cost=purchase, commission=commission,
                       promotion=promotion, first_leg=first_leg, last_mile=last_mile, tariff=tariff,
                       storage=storage, inventory_claim=claim, other_opex=other, gross_profit=gp,
                       gross_margin=gross_margin(gp, rev_cny))


def calc_platform_unit(drivers: PlatformDrivers, cost: CostRates, inventory_claim_rate: Decimal,
                       other_opex_rate: Decimal, fx_rate: Decimal | None) -> PlatformResult:
    """平台渠道单元：广告费率即推广费用率；库存索赔率与其他运营费用率来自渠道站点比例（AC-F04-11）。"""
    qty = sales_qty(drivers.spu_count, drivers.avg_sales)
    rev_local = revenue_local(qty, drivers.avg_price, drivers.discount_rate)
    if fx_rate is None:
        return PlatformResult(sales_qty=qty, revenue_local=rev_local, lines=None)
    opex = OpexRates(refund_rate=drivers.refund_rate, commission_rate=drivers.commission_rate,
                     promotion_rate=drivers.ad_rate, inventory_claim_rate=inventory_claim_rate,
                     other_opex_rate=other_opex_rate)
    return PlatformResult(sales_qty=qty, revenue_local=rev_local,
                          lines=profit_lines(revenue_cny(rev_local, fx_rate), cost, opex))


def calc_b2b_unit(sales_local: Decimal, opex: OpexRates, cost: CostRates, fx_rate: Decimal | None) -> ProfitLines | None:
    """AC-F06-05：B 端人民币收入 = 销售额（本币）× 预算汇率，其余同平台渠道公式。"""
    if fx_rate is None:
        return None
    return profit_lines(revenue_cny(sales_local, fx_rate), cost, opex)


def company_net_profit(platform_gross_profit: Decimal, b2b_gross_profit: Decimal, dept_expense: Decimal,
                       other_pl: Decimal) -> Decimal:
    """AC-F06-07：公司净利润 = Σ平台渠道毛利 + ΣB 端毛利 − Σ部门费用（含专项）+ 公司层其他损益（损失为负）。"""
    return platform_gross_profit + b2b_gross_profit - dept_expense + other_pl


# ---------------------------------------------------------------------------
# 偏差拆分（AC-F10-03/04、DEC-024）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RevenueSplit:
    budget_revenue: Decimal
    actual_revenue: Decimal          # 金蝶实际人民币收入
    total_variance: Decimal          # 实际 − 预算
    volume: Decimal                  # 量差
    price: Decimal                   # 价差
    fx: Decimal | None               # 汇率差（缺当月平均汇率为空）
    basis: Decimal | None            # 口径差（同上）
    missing_fx: bool


def revenue_variance_split(*, budget_qty: Decimal, budget_avg_price: Decimal, budget_discount_rate: Decimal,
                           budget_fx: Decimal, actual_qty: Decimal, actual_revenue_local: Decimal,
                           actual_fx: Decimal | None, kingdee_revenue_cny: Decimal) -> RevenueSplit:
    """量差 =（实际销量 − 预算销量）× 预算净单价 × 预算汇率；
    价差 =（实际净单价 − 预算净单价）× 实际销量 × 预算汇率（实际净单价 = BI 本币收入 ÷ 实际销量）；
    汇率差 = 实际本币收入 ×（当月平均汇率 − 预算汇率）；
    口径差 = 金蝶实际人民币收入 − BI 本币收入 × 当月平均汇率；
    四项之和 = 金蝶实际 − 预算人民币收入。
    价差按（实际本币收入 − 预算净单价 × 实际销量）× 预算汇率计算，与定义恒等且避免除法误差。"""
    p_b = net_price(budget_avg_price, budget_discount_rate)
    budget_rev = budget_qty * p_b * budget_fx
    volume = (actual_qty - budget_qty) * p_b * budget_fx
    price = (actual_revenue_local - p_b * actual_qty) * budget_fx
    if actual_fx is None:
        fx = basis = None
    else:
        fx = actual_revenue_local * (actual_fx - budget_fx)
        basis = kingdee_revenue_cny - actual_revenue_local * actual_fx
    return RevenueSplit(budget_revenue=budget_rev, actual_revenue=kingdee_revenue_cny,
                        total_variance=kingdee_revenue_cny - budget_rev, volume=volume, price=price, fx=fx,
                        basis=basis, missing_fx=actual_fx is None)


def rate_variance(actual_fee: Decimal, actual_revenue_cny: Decimal, budget_rate: Decimal) -> Decimal | None:
    """AC-F10-04：费率差 =（实际费率 − 预算费率）× 实际人民币收入，实际费率 = 实际费用 ÷ 实际人民币收入。"""
    if actual_revenue_cny == 0:
        return None
    return (actual_fee / actual_revenue_cny - budget_rate) * actual_revenue_cny


# ---------------------------------------------------------------------------
# 比率类指标
# ---------------------------------------------------------------------------
def safe_ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """通用比值（达成率 = 实际 ÷ 预算等）；分母为 0 时为空。"""
    if denominator == 0:
        return None
    return numerator / denominator


def net_profit_achievement(actual_sum: Decimal, target_sum: Decimal) -> Decimal | None:
    """AC-F10-08：累计净利润达成率 = 实际合计 ÷ 同期目标合计；目标合计 ≤ 0 时为空（显示「—」）。"""
    if target_sum <= 0:
        return None
    return actual_sum / target_sum


def growth_rate(current: Decimal, prior: Decimal | None) -> Decimal | None:
    """AC-F10-09：增速 = 本期 ÷ 上年同期 − 1；上年同期未导入（None）或为 0 时为空。"""
    if prior is None or prior == 0:
        return None
    return current / prior - ONE


def expense_growth_exceeds(expense_growth: Decimal | None, revenue_growth: Decimal | None) -> bool:
    """AC-F10-09：部门费用增速 > 收入增速 时标红。"""
    return expense_growth is not None and revenue_growth is not None and expense_growth > revenue_growth


def net_margin(net_profit: Decimal, revenue: Decimal) -> Decimal | None:
    """净利润率 = 净利润 ÷ 人民币收入。"""
    return safe_ratio(net_profit, revenue)


def forecast_deviation_pp(forecast_margin: Decimal | None, actual_margin: Decimal | None) -> Decimal | None:
    """AC-F10-10：|快照预测净利润率 − 实际净利润率|，单位百分点。"""
    if forecast_margin is None or actual_margin is None:
        return None
    return abs(forecast_margin - actual_margin) * HUNDRED


def forecast_deviation_alert(deviation_pp: Decimal | None) -> bool:
    return deviation_pp is not None and deviation_pp > FORECAST_DEVIATION_ALERT_PP


def quota_usage(actual_cumulative: Decimal, annual_budget: Decimal) -> Decimal | None:
    """AC-F10-07：额度使用率 = 截至最近导入月累计实际 ÷ 全年预算。"""
    return safe_ratio(actual_cumulative, annual_budget)


def time_progress(imported_months: int) -> Decimal:
    """AC-F10-07：时间进度 = 最近导入月份数 ÷ 12。"""
    return Decimal(imported_months) / Decimal(12)


# ---------------------------------------------------------------------------
# 品效（AC-F10-06、DEC-025）
# ---------------------------------------------------------------------------
def budget_efficiency_local(avg_sales: Decimal, avg_price: Decimal, discount_rate: Decimal) -> Decimal:
    """单元级预算品效（本币）= 单 SPU 平均销量 × 平均单价 × (1 − 折扣率)。"""
    return avg_sales * net_price(avg_price, discount_rate)


def actual_efficiency_local(revenue_local_actual: Decimal, spu_count: int) -> Decimal | None:
    """单元级实际品效（本币）= 实际销售额（本币）÷ 实际 SPU 数；SPU 数为 0 时为空。"""
    if spu_count == 0:
        return None
    return revenue_local_actual / Decimal(spu_count)


def budget_efficiency_cny(units: Iterable[tuple[int, Decimal, Decimal, Decimal]]) -> Decimal | None:
    """汇总行预算品效（人民币）= Σ(销量 × 净单价 × 预算汇率) ÷ ΣSPU 数。units = (SPU 数, 销量, 净单价, 预算汇率)。"""
    total_spu, total = 0, ZERO
    for spu, qty, price, fx in units:
        total_spu += spu
        total += qty * price * fx
    return None if total_spu == 0 else total / Decimal(total_spu)


def actual_efficiency_cny(rows: Iterable[tuple[int, Decimal, Decimal]]) -> Decimal | None:
    """汇总行实际品效（人民币）= Σ(实际本币销售额 × 当月平均汇率) ÷ ΣSPU 数。rows = (SPU 数, 本币销售额, 当月平均汇率)。"""
    total_spu, total = 0, ZERO
    for spu, rev, fx in rows:
        total_spu += spu
        total += rev * fx
    return None if total_spu == 0 else total / Decimal(total_spu)


# ---------------------------------------------------------------------------
# BI 与金蝶核对（AC-F09-07）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Reconciliation:
    bi_cny: Decimal | None
    diff_rate: Decimal | None
    flagged: bool
    missing_fx: bool


def reconcile(bi_revenue_local: Decimal, actual_fx: Decimal | None, kingdee_revenue: Decimal) -> Reconciliation:
    """BI 折人民币 = BI 本币销售额 × 当月平均汇率；差异率 =（BI 折人民币 − 金蝶收入）÷ 金蝶收入；|差异率| > 3% 标红。"""
    if actual_fx is None:
        return Reconciliation(bi_cny=None, diff_rate=None, flagged=False, missing_fx=True)
    bi_cny = bi_revenue_local * actual_fx
    rate = safe_ratio(bi_cny - kingdee_revenue, kingdee_revenue)
    return Reconciliation(bi_cny=bi_cny, diff_rate=rate, flagged=rate is not None and abs(rate) > RECONCILE_ALERT_RATE,
                          missing_fx=False)


# ---------------------------------------------------------------------------
# 历史参考（AC-F05-02、AC-F05-04）
# ---------------------------------------------------------------------------
def prior_year_same_month(actuals: Mapping[date, Decimal], month: date) -> Decimal | None:
    """上年同月实际；未导入为空（显示「无历史数据」）。actuals 的键为月初日期。"""
    return actuals.get(month_start(month).replace(year=month.year - 1))


def recent_12_months_total(actuals: Mapping[date, Decimal], imported_months: Iterable[date]) -> Decimal | None:
    """最近 12 个已导入月份的实际合计；没有任何已导入月份时为空。科目在已导入月份无实际时按 0 计。"""
    recent = sorted(set(imported_months), reverse=True)[:12]
    if not recent:
        return None
    if not any(m in actuals for m in recent):
        return None
    return sum((actuals.get(m, ZERO) for m in recent), ZERO)


# ---------------------------------------------------------------------------
# 新老品、新渠道（AC-F02-04、AC-F13-01/02、DEC-023）
# ---------------------------------------------------------------------------
def is_new_product(month: date, first_listed_on: date) -> bool:
    """该月最后一天 < 首次上架日期 + 12 个月 → 新品，否则老品。"""
    return month_end(month) < add_months(first_listed_on, 12)


def new_channel_month_index(month: date, start_month: date | None) -> int | None:
    """新渠道期第 k 个月（1..12）；不在新渠道期返回 None。起始月 ≤ 该月 < 起始月 + 12 个月。"""
    if start_month is None:
        return None
    k = months_between(start_month, month) + 1
    return k if 1 <= k <= 12 else None


def is_new_channel_period(month: date, start_month: date | None) -> bool:
    return new_channel_month_index(month, start_month) is not None


def exceeds_ramp_limit(store_month_revenue_cny: Decimal, month: date, start_month: date | None,
                       limits: list[Decimal] | None) -> bool:
    """店铺月人民币收入 > 生效「新渠道放量上限」第 k 个月上限 → 超出；无生效规则或不在新渠道期不标注。"""
    k = new_channel_month_index(month, start_month)
    if k is None or not limits or k > len(limits):
        return False
    return store_month_revenue_cny > limits[k - 1]
