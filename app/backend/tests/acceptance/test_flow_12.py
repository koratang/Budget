"""FLOW-12 B 端客户填报（API 层验收）。期望值逐字取自 TDD验收契约.md FLOW-12：
按「月 × B 端客户」提供 6 个输入项，平台佣金率与库存索赔率初始为 0.00%；保存后人民币收入 ¥ 1,424,000.00 并同时显示
USD 200,000.00；退款 28,480.00、推广费用 42,720.00、其他运营费用 14,240.00、采购成本 783,200.00、头程 71,200.00、
尾程 28,480.00、仓储 14,240.00、关税 99,680.00、佣金 0.00、库存索赔 0.00；毛利 341,760.00，毛利率 24.00%
"""
from datetime import date

from sqlalchemy import select

from app.core.money import fmt_amount, fmt_percent
from app.models import B2bUnit
from tests.acceptance.e2_common import MAR, Ctx
from tests.g2.helpers import customer

EXPECTED = {"revenue_cny": "1,424,000.00", "refund": "28,480.00", "promotion": "42,720.00", "other_opex": "14,240.00",
            "purchase_cost": "783,200.00", "first_leg": "71,200.00", "last_mile": "28,480.00", "storage": "14,240.00",
            "tariff": "99,680.00", "commission": "0.00", "inventory_claim": "0.00", "gross_profit": "341,760.00"}


def test_flow_12(seeded, client):
    db = seeded
    ctx = Ctx(db, client)
    task = ctx.publish()
    ctx.preset_ferguson_ratios(task)
    fer = customer(db, "Ferguson").id
    base = f"/api/filling-units/{ctx.unit(task, 'B端 · 美国业务部')}"
    ctx.login("sunting")
    g = ctx.grid(f"{base}/grid")
    items = [r["key"].split("|")[1] for r in g["rows"] if r["kind"] == "input" and r["key"].startswith(f"b2b:{fer}|")]
    assert items == ["sales_local", "refund_rate", "promotion_rate", "other_opex_rate", "commission_rate",
                     "inventory_claim_rate"]
    v = lambda gg, item: next(r for r in gg["rows"] if r["key"] == f"b2b:{fer}|{item}")["values"][MAR]  # noqa: E731
    assert v(g, "commission_rate") == "0.00%" and v(g, "inventory_claim_rate") == "0.00%"
    ctx.fill_flow12_sales(task)
    g = ctx.grid(f"{base}/grid")
    assert v(g, "revenue_cny") == "1,424,000.00" and v(g, "sales_local") == "200,000.00"
    assert v(g, "gross_profit") == "341,760.00" and v(g, "gross_margin") == "24.00%"
    assert g["kpis"]["sales_local_display"] == "$ 200,000.00 USD"  # 同时显示 USD 200,000.00
    assert g["kpis"]["revenue_cny_display"] == "¥ 1,424,000.00"
    u = db.scalar(select(B2bUnit).where(B2bUnit.customer_id == fer, B2bUnit.month == date(2027, 3, 1)))
    db.refresh(u)
    assert {f: fmt_amount(getattr(u, f)) for f in EXPECTED} == EXPECTED
    assert fmt_percent(u.gross_margin, 2) == "24.00%"
