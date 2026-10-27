"""FLOW-21 两版本对比（AC-F08-08）：维度行只含收入、毛利及差额，净利润只在公司合计行；按数据范围过滤。
期望值逐字取自 TDD验收契约.md FLOW-21 行。"""
from app.models.enums import VersionType


def _monthly(total):
    return {m: (total[0] / 12, total[1] / 12) for m in range(1, 13)}


def test_flow_21_version_compare(g3):
    from decimal import Decimal as D
    g3.set_now("2027-03-15 10:00")
    common = {"Amazon-US-01": _monthly((D(8000000), D(1600000))), "HomeDepot-US-01": _monthly((D(3000000), D(600000)))}
    v1 = g3.make_version(stores={**common, "Wayfair-US-01": _monthly((D(10000000), D(2000000)))},
                         depts={"人力资源部": 1200000})
    v2 = g3.make_version(vtype=VersionType.ADJUSTED_TARGET, version_no=2, quarter=1,
                         stores={**common, "Wayfair-US-01": _monthly((D(5800000), D(1160000)))},
                         depts={"人力资源部": 1200000}, approved_at="2027-03-15 10:00")

    r = g3.client("林晓").get("/api/versions/compare", params={"a": v1.id, "b": v2.id, "dims": "channel"})
    assert r.status_code == 200, r.text
    data = r.json()
    wf = next(x for x in data["rows"] if x["store"] == "Wayfair-US-01")
    assert (wf["revenue_diff"], wf["revenue_diff_display"]) == ("-4200000", "−¥ 4,200,000.00")
    assert (wf["gross_diff"], wf["gross_diff_display"]) == ("-840000", "−¥ 840,000.00")
    assert all(x["net_display"] == "—" for x in data["rows"]) and data["total"]["net_display"] == "—"
    assert data["company"]["net_diff"] == "-840000"
    assert data["company"]["net_diff_display"] == "−¥ 840,000.00"
    assert data["total"]["revenue_diff"] == "-4200000"          # 维度行差额合计 = 合计行差额
    assert next(x for x in data["rows"] if x["store"] == "Amazon-US-01")["revenue_diff_display"] == "—"

    # 王浩：只含其范围内店铺行，无公司合计净利润
    r = g3.client("王浩").get("/api/versions/compare", params={"a": v1.id, "b": v2.id, "dims": "channel"})
    assert r.status_code == 200
    assert [x["store"] for x in r.json()["rows"]] == ["Amazon-US-01"] and r.json()["company"] is None

    # 同一版本拦截
    r = g3.client("林晓").get("/api/versions/compare", params={"a": v1.id, "b": v1.id})
    assert r.status_code == 422 and r.json()["message"] == "请选择两个不同的版本"
