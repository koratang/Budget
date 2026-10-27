"""FLOW-11：平台渠道驱动填报、取值范围校验、保存后计算（AC-F04-01/02、AC-F06-01~04、AC-F06-08）。

契约期望：表格按「月 × 店铺 × 站点 × 品类 × 新品/老品」提供上述 7 个输入项；保存后：销量 1,200；
收入 USD 86,400.00 与 ¥ 615,168.00 同时显示；退款 30,758.40、采购成本 184,550.40、佣金 92,275.20、
推广费用 73,820.16、头程 36,910.08、尾程 49,213.44、关税 24,606.72、仓储 12,303.36、库存索赔 6,151.68、
其他运营费用 18,455.04；毛利 98,426.88，毛利率 16.00%；人民币收入为 0 的单元毛利率显示「—」；
2.5 与 120 均不保存并提示允许范围（SPU 数量为大于等于 0 的整数、比率 0%–100%）
"""
from sqlalchemy import select

from app.core.money import fmt_amount, fmt_percent
from app.models import PlatformUnit
from tests.g2.helpers import (category_id, grid, login, minimal_units, publish, pu_key, row, save, store,
                              unit_by_name)

MAR = "2027-03"
DRIVERS = {"spu_count": "10", "avg_sales": "120", "avg_price": "80.00", "discount_rate": "10", "refund_rate": "5",
           "ad_rate": "12", "commission_rate": "15"}


def preset_ratios(client, db, task_id, category="浴室柜"):
    """陈思雨（成本比例）与蒋帆（物流比例）预置 Amazon · 美国 · 浴室柜 2027-03 的比例。"""
    amz = store(db, "Amazon-US-01")
    ccr = f"ccr:{amz.channel_id}:{amz.site_id}:{category_id(db, category)}"
    csr = f"csr:{amz.channel_id}:{amz.site_id}"
    login(client, db, "chensiyu")
    cost = unit_by_name(db, task_id, "成本比例（财务BP）").id
    r = save(client, cost, [(f"{ccr}|purchase_cost_rate", MAR, "30")], tab="platform")
    assert r.status_code == 200 and r.json()["errors"] == [], r.text
    r = save(client, cost, [(f"{csr}|inventory_claim_rate", MAR, "1"), (f"{csr}|other_opex_rate", MAR, "3")],
             tab="site")
    assert r.status_code == 200 and r.json()["errors"] == [], r.text
    login(client, db, "jiangfan")
    lg = unit_by_name(db, task_id, "物流比例（物流物控）").id
    r = save(client, lg, [(f"{ccr}|first_leg_rate", MAR, "6"), (f"{ccr}|last_mile_rate", MAR, "8"),
                          (f"{ccr}|storage_rate", MAR, "2"), (f"{ccr}|tariff_rate", MAR, "4")], tab="platform")
    assert r.status_code == 200 and r.json()["errors"] == [], r.text


def fill_flow11_drivers(client, db, unit_id):
    login(client, db, "wanghao")
    changes = [(pu_key(db, "Amazon-US-01", "浴室柜", True, k), MAR, v) for k, v in DRIVERS.items()]
    r = save(client, unit_id, changes)
    assert r.status_code == 200 and r.json()["errors"] == [], r.text
    return r.json()["grid"]


def test_flow_11_platform_drivers_and_calc(seeded, client):
    db = seeded
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    unit_id = unit_by_name(db, task_id, "Amazon-US-01").id
    preset_ratios(client, db, task_id)
    g = fill_flow11_drivers(client, db, unit_id)

    # 7 个输入项 × 5 品类 × 新/老品；按月 1–12 列
    inputs = [r for r in g["rows"] if r["kind"] == "input"]
    assert len(inputs) == 5 * 2 * 7
    assert {r["key"].split("|")[1] for r in inputs} == set(DRIVERS)
    assert [c["key"] for c in g["columns"] if c["kind"] == "value"][:12] == [f"2027-{m:02d}" for m in range(1, 13)]

    key = lambda item: pu_key(db, "Amazon-US-01", "浴室柜", True, item)  # noqa: E731
    assert row(g, key("sales_qty"))["values"][MAR] == "1,200"
    assert row(g, key("revenue_local"))["values"][MAR] == "86,400.00"
    assert row(g, key("revenue_cny"))["values"][MAR] == "615,168.00"
    assert row(g, key("gross_profit"))["values"][MAR] == "98,426.88"
    assert row(g, key("gross_margin"))["values"][MAR] == "16.00%"
    assert g["kpis"]["revenue_local_display"] == "$ 86,400.00 USD"  # 双币同时显示
    assert g["kpis"]["revenue_cny_display"] == "¥ 615,168.00"

    unit = db.scalar(select(PlatformUnit).where(PlatformUnit.store_id == store(db, "Amazon-US-01").id,
                                                PlatformUnit.category_id == category_id(db, "浴室柜"),
                                                PlatformUnit.is_new.is_(True), PlatformUnit.month == unit_month()))
    db.refresh(unit)
    expected = {"refund": "30,758.40", "purchase_cost": "184,550.40", "commission": "92,275.20",
                "promotion": "73,820.16", "first_leg": "36,910.08", "last_mile": "49,213.44", "tariff": "24,606.72",
                "storage": "12,303.36", "inventory_claim": "6,151.68", "other_opex": "18,455.04",
                "gross_profit": "98,426.88"}
    assert {k: fmt_amount(getattr(unit, k)) for k in expected} == expected
    assert fmt_percent(unit.gross_margin, 2) == "16.00%"
    # 人民币收入为 0 的单元毛利率显示「—」
    assert row(g, pu_key(db, "Amazon-US-01", "浴室柜", False, "gross_margin"))["values"][MAR] == "—"

    # 2.5 与 120 均不保存并提示允许范围
    r = save(client, unit_id, [(key("spu_count"), MAR, "2.5")], g)
    err = r.json()["errors"]
    assert len(err) == 1 and "大于等于 0 的整数" in err[0]["message"]
    r = save(client, unit_id, [(key("discount_rate"), MAR, "120")], g)
    err = r.json()["errors"]
    assert len(err) == 1 and "0%" in err[0]["message"] and "100%" in err[0]["message"]
    g = grid(client, unit_id)
    assert row(g, key("spu_count"))["values"][MAR] == "10"
    assert row(g, key("discount_rate"))["values"][MAR] == "10.00%"
    assert row(g, key("revenue_cny"))["values"][MAR] == "615,168.00"


def unit_month():
    from datetime import date
    return date(2027, 3, 1)
