"""FLOW-13：成本比例 / 物流比例 / 公司层其他损益 → 公司净利润（AC-F04-04/05/06/11、AC-F06-06/07）。

契约期望：成本比例页按「月 × 渠道 × 站点 × 品类」与「月 × B 端客户」提供采购成本占比，按「月 × 渠道 × 站点」提供
库存索赔率与其他运营费用率且作用于该渠道站点全部品类与新老品单元；物流页只有四项比例；填充全年后该组合 12 个月均为
30.00%（调整模式下已锁定月份不被改写）；2027-03 公司净利润 = 98,426.88 + 341,760.00 − 300,000.00 + (−33,000.00)
= 107,186.88；其他损益不出现在任何渠道、品类或部门行
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import insert, select

from app.models import (BudgetVersion, ChannelCategoryRatio, FillingUnit, ImportBatch, PlatformUnit,
                        TargetAdjustment, User)
from tests.g2.helpers import (account, category_id, grid, login, minimal_units, publish, pu_key, row, save, store,
                              uid, unit_by_name)
from tests.g2.test_flow_11 import DRIVERS, fill_flow11_drivers, preset_ratios
from tests.g2.test_flow_12 import fill_ferguson, preset_ferguson

MAR = "2027-03"
MONTHS = [f"2027-{m:02d}" for m in range(1, 13)]


def test_flow_13_ratios_other_pl_and_net_profit(seeded, client):
    db = seeded
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    cost = unit_by_name(db, task_id, "成本比例（财务BP）").id
    lg = unit_by_name(db, task_id, "物流比例（物流物控）").id
    amz = store(db, "Amazon-US-01")
    combo = f"ccr:{amz.channel_id}:{amz.site_id}:{category_id(db, '浴室柜')}"

    # 成本比例页三类维度
    login(client, db, "chensiyu")
    gp = grid(client, cost, "platform")
    assert {c["key"] for c in gp["columns"] if c["kind"] == "dim"} == {"channel", "site", "category"}
    assert {r["key"].split("|")[1] for r in gp["rows"]} == {"purchase_cost_rate"}
    gb = grid(client, cost, "b2b")
    assert {r["key"].split("|")[0].split(":")[0] for r in gb["rows"]} == {"b2bc"}
    gs = grid(client, cost, "site")
    assert {r["key"].split("|")[1] for r in gs["rows"]} == {"inventory_claim_rate", "other_opex_rate"}

    # 填充全年：12 个月均为 30.00%
    r = client.post(f"/api/filling-units/{cost}/fill-year", params={"tab": "platform"},
                    json={"row_key": f"{combo}|purchase_cost_rate", "value": "30"})
    assert r.status_code == 200, r.text
    assert [row(r.json()["grid"], f"{combo}|purchase_cost_rate")["values"][m] for m in MONTHS] == ["30.00%"] * 12

    # 物流页只有四项比例（无收入、销量、利润列）
    login(client, db, "jiangfan")
    gl = grid(client, lg, "platform")
    assert {r["key"].split("|")[1] for r in gl["rows"]} == {"first_leg_rate", "last_mile_rate", "storage_rate",
                                                            "tariff_rate"}
    labels = " ".join(c["label"] for c in gl["columns"])
    assert not any(w in labels for w in ("收入", "销量", "利润"))
    assert client.get(f"/api/filling-units/{cost}/grid").status_code == 403  # 物流物控看不到成本比例

    # FLOW-11 单元 + 同站点另一品类单元（验证库存索赔 / 其他运营费用率作用于全部品类与新老品）
    unit_id = unit_by_name(db, task_id, "Amazon-US-01").id
    fill_flow11_drivers(client, db, unit_id)
    login(client, db, "wanghao")
    other_key = lambda item: pu_key(db, "Amazon-US-01", "框镜", False, item)  # noqa: E731
    r = save(client, unit_id, [(other_key(k), MAR, v) for k, v in DRIVERS.items()])
    assert r.json()["errors"] == []
    preset_ratios(client, db, task_id)
    for cat, is_new in (("浴室柜", True), ("框镜", False)):
        u = db.scalar(select(PlatformUnit).where(PlatformUnit.store_id == amz.id, PlatformUnit.is_new.is_(is_new),
                                                 PlatformUnit.category_id == category_id(db, cat),
                                                 PlatformUnit.month == date(2027, 3, 1)))
        db.refresh(u)
        assert u.inventory_claim == u.revenue_cny * Decimal("0.01")
        assert u.other_opex == u.revenue_cny * Decimal("0.03")
    # 只保留 FLOW-11 单元：把框镜老品清零
    login(client, db, "wanghao")
    r = save(client, unit_id, [(other_key("spu_count"), MAR, "0")])
    assert r.json()["errors"] == []

    # FLOW-12 客户
    preset_ferguson(client, db, task_id)
    fill_ferguson(client, db, unit_by_name(db, task_id, "B端 · 美国业务部").id)

    # 公司层其他损益 2027-03
    login(client, db, "chensiyu")
    r = save(client, cost, [("opl|finance_cost", MAR, "-5,000.00"), ("opl|fx_gain_loss", MAR, "2,000.00"),
                            ("opl|non_operating", MAR, "0.00"), ("opl|income_tax", MAR, "-30,000.00")], tab="other")
    assert r.json()["errors"] == [], r.text
    assert row(r.json()["grid"], "total|other_pl")["values"][MAR] == "−33,000.00"

    # 人力资源部 2027-03 部门费用合计 300,000.00
    login(client, db, "zhengke")
    hr = unit_by_name(db, task_id, "人力资源部").id
    r = save(client, hr, [(f"de:{account(db, '工资薪酬').id}|amount", MAR, "300000")])
    assert r.json()["errors"] == [], r.text

    login(client, db, "linxiao")
    version_id = db.get(FillingUnit, cost).version_id
    pl = client.get(f"/api/versions/{version_id}/pl").json()
    mar = next(m for m in pl["months"] if m["month"] == MAR)
    assert mar["platform_gross_profit_display"] == "98,426.88"
    assert mar["b2b_gross_profit_display"] == "341,760.00"
    assert mar["dept_expense_display"] == "300,000.00"
    assert mar["other_pl_display"] == "−33,000.00"
    assert mar["net_profit_display"] == "107,186.88"
    # 其他损益不出现在任何渠道、品类或部门行
    for seg in pl["channels"] + pl["customers"]:
        assert not any("other" in k for k in seg)


def test_flow_13_fill_year_skips_months_with_actuals_in_adjustment(seeded, client):
    """调整模式下已锁定月份不被改写：已导入 2027-01～04 金蝶实际时，填充全年只写入 5–12 月。"""
    db = seeded
    amz = store(db, "Amazon-US-01")
    cat = category_id(db, "浴室柜")
    v = BudgetVersion(year=2027, type="adjustment_draft", version_no=1, name="2027 年第二季度调整稿")
    db.add(v)
    db.flush()
    adj = TargetAdjustment(year=2027, quarter=2, status="in_progress", draft_version_id=v.id)
    db.add(adj)
    db.flush()
    bp, head = uid(db, "chensiyu"), uid(db, "linxiao")
    unit = FillingUnit(adjustment_id=adj.id, version_id=v.id, unit_type="cost_ratio", name="成本比例（财务BP）",
                       filler_id=bp, reviewer_id=head, status="adjusting")
    db.add(unit)
    db.execute(insert(ChannelCategoryRatio), [dict(version_id=v.id, month=date(2027, m, 1), channel_id=amz.channel_id,
                                                   site_id=amz.site_id, category_id=cat,
                                                   purchase_cost_rate=Decimal("0.25")) for m in range(1, 13)])
    for m in range(1, 5):
        db.add(ImportBatch(source="kingdee", period=date(2027, m, 1), file_name=f"金蝶_2027-{m:02d}_利润表.xlsx",
                           status="effective", uploaded_by=db.get(User, bp).id))
    db.flush()
    login(client, db, "chensiyu")
    combo = f"ccr:{amz.channel_id}:{amz.site_id}:{cat}"
    r = client.post(f"/api/filling-units/{unit.id}/fill-year", params={"tab": "platform"},
                    json={"row_key": f"{combo}|purchase_cost_rate", "value": "30"})
    assert r.status_code == 200, r.text
    vals = row(r.json()["grid"], f"{combo}|purchase_cost_rate")["values"]
    assert [vals[m] for m in MONTHS[:4]] == ["25.00%"] * 4
    assert [vals[m] for m in MONTHS[4:]] == ["30.00%"] * 8
