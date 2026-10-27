"""FLOW-13 成本比例 / 物流比例 / 公司层其他损益 → 公司净利润（API 层验收）。期望值逐字取自 TDD验收契约.md FLOW-13：
成本比例页按「月 × 渠道 × 站点 × 品类」与「月 × B 端客户」提供采购成本占比，按「月 × 渠道 × 站点」提供库存索赔率与
其他运营费用率且作用于该渠道站点全部品类与新老品单元；物流页只有四项比例；填充全年后该组合 12 个月均为 30.00%
（调整模式下已锁定月份不被改写）；2027-03 公司净利润 = 98,426.88 + 341,760.00 − 300,000.00 + (−33,000.00) = 107,186.88；
其他损益不出现在任何渠道、品类或部门行
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import FillingUnit, PlatformUnit
from tests.acceptance.e2_common import FLOW11_DRIVERS, MAR, Ctx, actual_rows_2027
from tests.g2.helpers import category_id, pu_key, store

MONTHS = [f"2027-{m:02d}" for m in range(1, 13)]


def _vals(g, key):
    return next(r for r in g["rows"] if r["key"] == key)["values"]


def test_flow_13(seeded, client):
    db = seeded
    ctx = Ctx(db, client)
    task = ctx.publish()
    amz = store(db, "Amazon-US-01")
    combo = f"ccr:{amz.channel_id}:{amz.site_id}:{category_id(db, '浴室柜')}"
    csr = f"csr:{amz.channel_id}:{amz.site_id}"
    cost = f"/api/filling-units/{ctx.unit(task, '成本比例（财务BP）')}"
    lg = f"/api/filling-units/{ctx.unit(task, '物流比例（物流物控）')}"

    ctx.login("chensiyu")
    gp, gb, gs = ctx.grid(f"{cost}/grid", "platform"), ctx.grid(f"{cost}/grid", "b2b"), ctx.grid(f"{cost}/grid", "site")
    assert [c["key"] for c in gp["columns"] if c["kind"] == "dim"] == ["channel", "site", "category"]
    assert {r["key"].split("|")[1] for r in gp["rows"] if r["kind"] == "input"} == {"purchase_cost_rate"}
    assert {r["key"].split(":")[0] for r in gb["rows"] if r["kind"] == "input"} == {"b2bc"}
    assert {r["key"].split("|")[1] for r in gs["rows"] if r["kind"] == "input"} == {"inventory_claim_rate",
                                                                                   "other_opex_rate"}
    assert [c["key"] for c in gs["columns"] if c["kind"] == "dim"][:2] == ["channel", "site"]
    r = client.post(f"{cost}/fill-year", params={"tab": "platform"},
                    json={"row_key": f"{combo}|purchase_cost_rate", "value": "30"})
    assert r.status_code == 200, r.text
    assert [_vals(r.json()["grid"], f"{combo}|purchase_cost_rate")[m] for m in MONTHS] == ["30.00%"] * 12
    ctx.save_ok(cost, [(f"{csr}|inventory_claim_rate", MAR, "1"), (f"{csr}|other_opex_rate", MAR, "3")], tab="site")
    g = ctx.save_ok(cost, [("opl|finance_cost", MAR, "-5,000.00"), ("opl|fx_gain_loss", MAR, "2,000.00"),
                           ("opl|non_operating", MAR, "0.00"), ("opl|income_tax", MAR, "-30,000.00")], tab="other")
    assert _vals(g, "total|other_pl")[MAR] == "−33,000.00"

    ctx.login("jiangfan")
    gl = ctx.grid(f"{lg}/grid", "platform")
    assert {r["key"].split("|")[1] for r in gl["rows"] if r["kind"] == "input"} == {
        "first_leg_rate", "last_mile_rate", "storage_rate", "tariff_rate"}
    labels = " ".join(c["label"] for c in gl["columns"]) + " ".join(str(r["values"].get("item", "")) for r in gl["rows"])
    assert not any(w in labels for w in ("收入", "销量", "利润"))
    ctx.save_ok(lg, [(f"{combo}|first_leg_rate", MAR, "6"), (f"{combo}|last_mile_rate", MAR, "8"),
                     (f"{combo}|storage_rate", MAR, "2"), (f"{combo}|tariff_rate", MAR, "4")], tab="platform")

    # 该月公司只有 FLOW-11 单元与 FLOW-12 客户；人力资源部 300,000.00
    ctx.fill_flow11_drivers(task)
    ctx.preset_ferguson_ratios(task)
    ctx.fill_flow12_sales(task)
    ctx.fill_hr_300k(task)

    # 库存索赔率 / 其他运营费用率作用于该渠道站点全部品类与新老品：另一品类老品单元同样按 1% / 3%
    ctx.login("wanghao")
    unit_url = f"/api/filling-units/{ctx.unit(task, 'Amazon-US-01')}"
    other = lambda i: pu_key(db, "Amazon-US-01", "框镜", False, i)  # noqa: E731
    ctx.save_ok(unit_url, [(other(i), MAR, v) for i, v in FLOW11_DRIVERS.items()])
    for cat, new in (("浴室柜", True), ("框镜", False)):
        u = db.scalar(select(PlatformUnit).where(PlatformUnit.store_id == amz.id, PlatformUnit.is_new.is_(new),
                                                 PlatformUnit.category_id == category_id(db, cat),
                                                 PlatformUnit.month == date(2027, 3, 1)))
        db.refresh(u)
        assert u.inventory_claim == u.revenue_cny * Decimal("0.01") and u.other_opex == u.revenue_cny * Decimal("0.03")
    ctx.save_ok(unit_url, [(other("spu_count"), MAR, "0")])  # 恢复为只有 FLOW-11 单元

    ctx.login("linxiao")
    vid = db.get(FillingUnit, ctx.unit(task, "成本比例（财务BP）")).version_id
    pl = client.get(f"/api/versions/{vid}/pl").json()
    mar = next(m for m in pl["months"] if m["month"] == MAR)
    assert (mar["platform_gross_profit_display"], mar["b2b_gross_profit_display"], mar["dept_expense_display"],
            mar["other_pl_display"], mar["net_profit_display"]) == (
        "98,426.88", "341,760.00", "300,000.00", "−33,000.00", "107,186.88")
    for seg in pl["channels"] + pl["customers"]:
        assert not any("other_pl" in k or "finance_cost" in k or "income_tax" in k for k in seg)


def test_flow_13_fill_year_in_adjustment_skips_actual_months(seeded, client):
    """调整模式下已锁定月份不被改写：真实发起 Q2 调整（已导入 1–4 月实际），财务BP 填充全年只写 5–12 月。"""
    db = seeded
    ctx = Ctx(db, client)
    ctx.build_v1()
    ctx.now("2027-05-10 16:00")
    ctx.import_kingdee(actual_rows_2027([1, 2, 3, 4]), "金蝶_2027-01至04_利润表.xlsx")
    ctx.now("2027-05-12 09:00")
    ctx.login("linxiao")
    adj = client.post("/api/versions/adjustments").json()["id"]
    unit = db.scalar(select(FillingUnit).where(FillingUnit.adjustment_id == adj, FillingUnit.unit_type == "cost_ratio"))
    amz = store(db, "Amazon-US-01")
    combo = f"ccr:{amz.channel_id}:{amz.site_id}:{category_id(db, '浴室柜')}"
    ctx.login("chensiyu")
    before = _vals(ctx.grid(f"/api/filling-units/{unit.id}/grid", "platform"), f"{combo}|purchase_cost_rate")
    r = client.post(f"/api/filling-units/{unit.id}/fill-year", params={"tab": "platform"},
                    json={"row_key": f"{combo}|purchase_cost_rate", "value": "30"})
    assert r.status_code == 200, r.text
    vals = _vals(r.json()["grid"], f"{combo}|purchase_cost_rate")
    assert [vals[m] for m in MONTHS[:4]] == [before[m] for m in MONTHS[:4]]
    assert [vals[m] for m in MONTHS[4:]] == ["30.00%"] * 8
