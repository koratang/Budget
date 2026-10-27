"""FLOW-21 版本对比（REQ-F08-03、AC-F08-08）：真实路由 + 权限 + 数据库。期望值逐字取自 TDD验收契约.md FLOW-21。"""
from tests.acceptance.e3_scenarios import flow21
from tests.g3.conftest import g3  # noqa: F401  （fixture）


def test_flow_21(g3):  # noqa: F811
    g3.set_now("2027-03-15 10:00")
    v1, v2 = flow21(g3)

    # 林晓选 V1、V2 按「渠道 × 店铺 × 站点」对比
    r = g3.client("林晓").get("/api/versions/compare", params={"a": v1.id, "b": v2.id, "dims": "channel"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["dims_label"] == "渠道 × 店铺 × 站点"
    wf = next(x for x in data["rows"] if x["store"] == "Wayfair-US-01")
    assert wf["revenue_diff_display"] == "−¥ 4,200,000.00"      # 收入差额 −4,200,000.00
    assert wf["gross_diff_display"] == "−¥ 840,000.00"          # 毛利差额 −840,000.00
    # 维度行与维度合计行净利润显示「—」
    assert all(x["net_display"] == "—" for x in data["rows"])
    assert data["total"]["net_display"] == "—"
    # 只有公司合计行显示两版净利润及差额 −840,000.00
    company = data["company"]
    assert company["net_a_display"].startswith("¥ ") and company["net_b_display"].startswith("¥ ")
    assert company["net_diff_display"] == "−¥ 840,000.00"
    # 其他维度不变：差额 0
    for name in ("Amazon-US-01", "HomeDepot-US-01"):
        row = next(x for x in data["rows"] if x["store"] == name)
        assert row["revenue_diff"] == "0" and row["gross_diff"] == "0"

    # 王浩做同样对比：结果只含其范围内店铺行（Amazon-US-01），无公司合计
    r = g3.client("王浩").get("/api/versions/compare", params={"a": v1.id, "b": v2.id, "dims": "channel"})
    assert r.status_code == 200, r.text
    assert [x["store"] for x in r.json()["rows"]] == ["Amazon-US-01"]
    assert r.json()["company"] is None
