"""FLOW-25 渠道×站点偏差：对比基准、报告内容、B 端分组、未归属渠道、量价汇率口径拆分、费率差、BI 未到。

期望值逐字取自 TDD验收契约.md FLOW-25 行。
"""
from decimal import Decimal

from app.calc import formulas as F
from app.core.money import fmt_amount, round_to

from tests.g4 import builders as B
from tests.g4.scenarios import flow25


def money(v: str | None) -> str:
    return fmt_amount(Decimal(v)) if v is not None else "—"


def rate2(v: str) -> str:
    return f"{round_to(Decimal(v), 2)}%"


def find(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_split_formulas_unit():
    """单元测试：拆分公式（量差、价差、汇率差、口径差、费率差）。"""
    sp = F.revenue_variance_split(budget_qty=Decimal("1200"), budget_avg_price=Decimal("80.00"),
                                  budget_discount_rate=Decimal("0.10"), budget_fx=Decimal("7.12"),
                                  actual_qty=Decimal("1100"), actual_revenue_local=Decimal("77000.00"),
                                  actual_fx=Decimal("7.2000"), kingdee_revenue_cny=Decimal("554400.00"))
    assert fmt_amount(sp.budget_revenue) == "615,168.00"
    assert fmt_amount(sp.volume) == "−51,264.00"
    assert fmt_amount(sp.price) == "−15,664.00"
    assert fmt_amount(sp.fx) == "6,160.00"
    assert fmt_amount(sp.basis) == "0.00"
    assert fmt_amount(sp.volume + sp.price + sp.fx + sp.basis) == "−60,768.00"
    rd = F.rate_variance(Decimal("73000.00"), Decimal("554400.00"), Decimal("0.12"))
    assert fmt_amount(rd) == "6,472.00"


def test_channel_report_default_baseline_and_split(client, seeded):
    db = seeded
    flow25(db)
    B.login(client, db, "linxiao")
    r = client.get("/api/reports/channel-site", params={"month": "2027-04"})
    assert r.status_code == 200, r.text
    data = r.json()
    # 对比基准默认「最新调整后目标」，可切换年初原始目标与最新滚动预测
    assert data["baseline"] == "adj"
    assert data["baseline_label"] == "V2 2027Q2 目标调整"
    assert [o["label"] for o in data["baseline_options"]] == ["年初原始目标", "最新调整后目标", "最新滚动预测"]
    assert data["bi_available"] is True

    us = find(data["rows"], "Amazon-US-01")
    rev = us["revenue"]
    assert money(rev["budget"]) == "615,168.00"
    assert money(rev["actual"]) == "554,400.00"
    assert money(rev["diff"]) == "−60,768.00"
    assert rate2(rev["rate"]) == "90.12%"
    sp = us["split"]
    assert money(sp["volume"]) == "−51,264.00"
    assert money(sp["price"]) == "−15,664.00"
    assert money(sp["fx"]) == "6,160.00"
    assert money(sp["basis"]) == "0.00"
    total = sum(Decimal(sp[k]) for k in ("volume", "price", "fx", "basis"))
    assert fmt_amount(total) == "−60,768.00"
    promo = next(line for line in us["lines"] if line["label"] == "推广费用")
    assert money(promo["rate_diff"]) == "6,472.00"
    # 行内显示收入、退款、各项费用、毛利、毛利率的预算、实际、差额、达成率（毛利率为百分点差）
    assert [line["label"] for line in us["lines"]] == ["退款", "采购成本", "佣金", "推广费用", "头程费", "尾程费",
                                                       "关税", "仓储费", "库存索赔", "其他运营费用"]
    for line in us["lines"]:
        assert {"budget", "actual", "diff", "rate"} <= set(line)
    assert set(us["gross_profit"]) == {"budget", "actual", "diff", "rate"}
    gm = us["gross_margin"]
    assert gm["diff_pp"] is not None
    assert Decimal(gm["diff_pp"]) == (Decimal(gm["actual"]) - Decimal(gm["budget"]))
    # 「B 端（按客户）」分组下 Ferguson 一行；「未归属渠道」行单列
    assert [c["name"] for c in data["b2b_rows"]] == ["Ferguson"]
    assert data["b2b_rows"][0]["channel"] == "B 端 · 美国业务部"
    un = data["unassigned"]
    assert un["name"] == "未归属渠道"
    assert [(line["label"], money(line["actual"])) for line in un["lines"]] == [("仓储费", "12,000.00")]
    assert data["total"]["label"] == "合计（含 B 端与未归属渠道）"


def test_channel_report_baseline_switch(client, seeded):
    db = seeded
    flow25(db)
    B.login(client, db, "linxiao")
    orig = client.get("/api/reports/channel-site", params={"month": "2027-04", "baseline": "orig"}).json()
    roll = client.get("/api/reports/channel-site", params={"month": "2027-04", "baseline": "roll"}).json()
    assert orig["baseline_label"] == "V1 年初原始目标"
    assert roll["baseline_label"] == "Q2 滚动预测快照"
    # 年初原始目标销量 1,300、滚动预测 1,100：预算收入随基准变化
    assert money(find(orig["rows"], "Amazon-US-01")["revenue"]["budget"]) == "666,432.00"
    assert money(find(roll["rows"], "Amazon-US-01")["revenue"]["budget"]) == "563,904.00"


def test_channel_report_defaults_to_original_without_adjustment(client, seeded):
    db = seeded
    flow25(db, with_adjustment=False)
    B.login(client, db, "linxiao")
    data = client.get("/api/reports/channel-site", params={"month": "2027-04"}).json()
    assert data["baseline"] == "adj"
    assert data["baseline_label"] == "V1 年初原始目标（本年度暂无调整，取年初原始目标）"
    assert money(find(data["rows"], "Amazon-US-01")["revenue"]["budget"]) == "666,432.00"


def test_channel_report_bi_missing_month(client, seeded):
    db = seeded
    flow25(db)
    B.login(client, db, "linxiao")
    data = client.get("/api/reports/channel-site", params={"month": "2027-05"}).json()
    assert data["bi_available"] is False
    assert data["bi_notice"] == "量价拆分待 BI 数据（最近 BI 数据截至 2027-04）"
    us = find(data["rows"], "Amazon-US-01")
    assert us["split"] is None and data["total"]["split"] is None
    assert all(line["rate_diff"] is None and line["budget_rate"] is None for line in us["lines"])
    # 只显示金额差
    assert money(us["revenue"]["actual"]) == "500,000.00"
    assert us["revenue"]["diff"] is not None


def test_channel_report_scope_and_forbidden(client, seeded):
    db = seeded
    flow25(db)
    B.login(client, db, "wanghao")
    data = client.get("/api/reports/channel-site", params={"month": "2027-04"}).json()
    assert [r["name"] for r in data["rows"]] == ["Amazon-US-01"]
    assert data["b2b_rows"] == [] and data["unassigned"] is None
    assert data["total"]["label"] == "合计（当前范围）"
    # 无任何渠道 / 店铺 / 客户范围的角色：403 且不含记录字段
    B.login(client, db, "wujing")
    r = client.get("/api/reports/channel-site", params={"month": "2027-04"})
    assert r.status_code == 403 and r.json() == {"code": "forbidden", "message": "无权限"}
