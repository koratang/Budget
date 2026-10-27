"""FLOW-11 平台渠道驱动填报与保存后计算（API 层验收）。期望值逐字取自 TDD验收契约.md FLOW-11：
表格按「月 × 店铺 × 站点 × 品类 × 新品/老品」提供上述 7 个输入项；保存后：销量 1,200；收入 USD 86,400.00 与 ¥ 615,168.00
同时显示；退款 30,758.40、采购成本 184,550.40、佣金 92,275.20、推广费用 73,820.16、头程 36,910.08、尾程 49,213.44、
关税 24,606.72、仓储 12,303.36、库存索赔 6,151.68、其他运营费用 18,455.04；毛利 98,426.88，毛利率 16.00%；
人民币收入为 0 的单元毛利率显示「—」；2.5 与 120 均不保存并提示允许范围（SPU 数量为大于等于 0 的整数、比率 0%–100%）
"""
from datetime import date

from sqlalchemy import select

from app.core.money import fmt_amount, fmt_percent
from app.models import PlatformUnit
from tests.acceptance.e2_common import FLOW11_DRIVERS, MAR, Ctx
from tests.g2.helpers import category_id, pu_key, store

EXPECTED = {"refund": "30,758.40", "purchase_cost": "184,550.40", "commission": "92,275.20", "promotion": "73,820.16",
            "first_leg": "36,910.08", "last_mile": "49,213.44", "tariff": "24,606.72", "storage": "12,303.36",
            "inventory_claim": "6,151.68", "other_opex": "18,455.04", "gross_profit": "98,426.88"}


def test_flow_11(seeded, client):
    db = seeded
    ctx = Ctx(db, client)
    task = ctx.publish()
    ctx.preset_flow11_ratios(task)
    base = f"/api/filling-units/{ctx.unit(task, 'Amazon-US-01')}"
    ctx.login("wanghao")
    g = ctx.grid(f"{base}/grid")
    # 单位即店铺（页头显示渠道、站点、结算币种），表格维度为品类 × 新/老品 × 项目，按月列
    assert (g["store"]["name"], g["store"]["site"], g["store"]["currency"]) == ("Amazon-US-01", "美国", "USD")
    assert [c["label"] for c in g["columns"] if c["kind"] == "dim"][:2] == ["品类", "新/老品"]
    assert [c["key"] for c in g["columns"] if c["kind"] == "value"][:12] == [f"2027-{m:02d}" for m in range(1, 13)]
    inputs = [r for r in g["rows"] if r["kind"] == "input"]
    assert {r["key"].split("|")[1] for r in inputs} == set(FLOW11_DRIVERS) and len(inputs) == 5 * 2 * 7

    k = lambda item, new=True: pu_key(db, "Amazon-US-01", "浴室柜", new, item)  # noqa: E731
    g = ctx.save_ok(base, [(k(i), MAR, v) for i, v in FLOW11_DRIVERS.items()])
    val = lambda item, new=True: next(r for r in g["rows"] if r["key"] == k(item, new))["values"][MAR]  # noqa: E731
    assert val("sales_qty") == "1,200"
    assert val("revenue_local") == "86,400.00" and val("revenue_cny") == "615,168.00"
    assert val("gross_profit") == "98,426.88" and val("gross_margin") == "16.00%"
    assert g["kpis"]["revenue_local_display"] == "$ 86,400.00 USD" and g["kpis"]["revenue_cny_display"] == "¥ 615,168.00"
    assert val("gross_margin", new=False) == "—"  # 人民币收入为 0 的单元
    u = db.scalar(select(PlatformUnit).where(PlatformUnit.store_id == store(db, "Amazon-US-01").id,
                                             PlatformUnit.category_id == category_id(db, "浴室柜"),
                                             PlatformUnit.is_new.is_(True), PlatformUnit.month == date(2027, 3, 1)))
    db.refresh(u)
    assert {f: fmt_amount(getattr(u, f)) for f in EXPECTED} == EXPECTED
    assert fmt_percent(u.gross_margin, 2) == "16.00%"

    r = ctx.save(base, [(k("spu_count"), MAR, "2.5")])
    assert [e["message"] for e in r.json()["errors"]] and "大于等于 0 的整数" in r.json()["errors"][0]["message"]
    r = ctx.save(base, [(k("discount_rate"), MAR, "120")])
    assert "0% 到 100%" in r.json()["errors"][0]["message"]
    g = ctx.grid(f"{base}/grid")
    assert val("spu_count") == "10" and next(r for r in g["rows"] if r["key"] == k("discount_rate"))["values"][MAR] == "10.00%"
    db.refresh(u)
    assert u.spu_count == 10 and fmt_amount(u.revenue_cny) == "615,168.00"
