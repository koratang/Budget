"""FLOW-12：B 端客户填报（AC-F04-03、AC-F06-05、AC-F06-08）。

契约期望：按「月 × B 端客户」提供 6 个输入项，平台佣金率与库存索赔率初始为 0.00%；保存后人民币收入
¥ 1,424,000.00 并同时显示 USD 200,000.00；退款 28,480.00、推广费用 42,720.00、其他运营费用 14,240.00、
采购成本 783,200.00、头程 71,200.00、尾程 28,480.00、仓储 14,240.00、关税 99,680.00、佣金 0.00、库存索赔 0.00；
毛利 341,760.00，毛利率 24.00%
"""
from datetime import date

from sqlalchemy import select

from app.core.money import fmt_amount, fmt_foreign, fmt_percent
from app.models import B2bUnit
from tests.g2.helpers import customer, grid, login, minimal_units, publish, row, save, unit_by_name

MAR = "2027-03"


def preset_ferguson(client, db, task_id):
    fer = customer(db, "Ferguson").id
    login(client, db, "chensiyu")
    cost = unit_by_name(db, task_id, "成本比例（财务BP）").id
    r = save(client, cost, [(f"b2bc:{fer}|purchase_cost_rate", MAR, "55")], tab="b2b")
    assert r.json()["errors"] == [], r.text
    login(client, db, "jiangfan")
    lg = unit_by_name(db, task_id, "物流比例（物流物控）").id
    r = save(client, lg, [(f"b2bc:{fer}|first_leg_rate", MAR, "5"), (f"b2bc:{fer}|last_mile_rate", MAR, "2"),
                          (f"b2bc:{fer}|storage_rate", MAR, "1"), (f"b2bc:{fer}|tariff_rate", MAR, "7")], tab="b2b")
    assert r.json()["errors"] == [], r.text


def fill_ferguson(client, db, unit_id):
    fer = customer(db, "Ferguson").id
    login(client, db, "sunting")
    r = save(client, unit_id, [(f"b2b:{fer}|sales_local", MAR, "200,000.00"), (f"b2b:{fer}|refund_rate", MAR, "2"),
                               (f"b2b:{fer}|promotion_rate", MAR, "3"), (f"b2b:{fer}|other_opex_rate", MAR, "1")])
    assert r.status_code == 200 and r.json()["errors"] == [], r.text
    return r.json()["grid"]


def test_flow_12_b2b_customer(seeded, client):
    db = seeded
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    unit_id = unit_by_name(db, task_id, "B端 · 美国业务部").id
    fer = customer(db, "Ferguson").id
    login(client, db, "sunting")
    g = grid(client, unit_id)
    items = [r["key"].split("|")[1] for r in g["rows"] if r["kind"] == "input" and r["key"].startswith(f"b2b:{fer}|")]
    assert items == ["sales_local", "refund_rate", "promotion_rate", "other_opex_rate", "commission_rate",
                     "inventory_claim_rate"]
    assert row(g, f"b2b:{fer}|commission_rate")["values"][MAR] == "0.00%"
    assert row(g, f"b2b:{fer}|inventory_claim_rate")["values"][MAR] == "0.00%"

    preset_ferguson(client, db, task_id)
    g = fill_ferguson(client, db, unit_id)
    assert row(g, f"b2b:{fer}|revenue_cny")["values"][MAR] == "1,424,000.00"
    assert row(g, f"b2b:{fer}|sales_local")["values"][MAR] == "200,000.00"
    assert row(g, f"b2b:{fer}|gross_profit")["values"][MAR] == "341,760.00"
    assert row(g, f"b2b:{fer}|gross_margin")["values"][MAR] == "24.00%"

    u = db.scalar(select(B2bUnit).where(B2bUnit.customer_id == fer, B2bUnit.month == date(2027, 3, 1)))
    db.refresh(u)
    assert fmt_foreign(u.sales_local, "USD") == "$ 200,000.00 USD"
    expected = {"revenue_cny": "1,424,000.00", "refund": "28,480.00", "promotion": "42,720.00",
                "other_opex": "14,240.00", "purchase_cost": "783,200.00", "first_leg": "71,200.00",
                "last_mile": "28,480.00", "storage": "14,240.00", "tariff": "99,680.00", "commission": "0.00",
                "inventory_claim": "0.00", "gross_profit": "341,760.00"}
    assert {k: fmt_amount(getattr(u, k)) for k in expected} == expected
    assert fmt_percent(u.gross_margin, 2) == "24.00%"
