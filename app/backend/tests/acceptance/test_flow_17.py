"""FLOW-17 新渠道超放量标注与理由（API 层验收）。期望值逐字取自 TDD验收契约.md FLOW-17：
2027-04 单元标注「超出新渠道放量规则」，2027-03 不标注；未填理由时提交被阻止并指出 2027-04；填写理由后提交成功，状态变为已提交
"""
from tests.acceptance.e2_common import Ctx
from tests.g2.helpers import minimal_units, pu_key
from tests.g2.test_flow_17 import setup_rule_and_store

# 2027-04：6 × 90.8 × 90.23 USD × 7.12 = 350,000.00；2027-03：6 × 116.01 × 36.32 USD × 7.12 = 180,000.00
CELLS = [("spu_count", "2027-04", "6"), ("avg_sales", "2027-04", "90.8"), ("avg_price", "2027-04", "90.23"),
         ("spu_count", "2027-03", "6"), ("avg_sales", "2027-03", "116.01"), ("avg_price", "2027-03", "36.32")]


def test_flow_17(seeded, client):
    db = seeded
    ctx = Ctx(db, client)
    setup_rule_and_store(db)  # 生效的额度标准规则（第 1 月 200,000.00、第 2 月 300,000.00）；TikTok-US-01 起始 2027-03
    task = ctx.publish(minimal_units(db, stores=("Amazon-US-01", "TikTok-US-01")))
    url = f"/api/filling-units/{ctx.unit(task, 'TikTok-US-01')}"
    ctx.login("wanghao")
    g = ctx.save_ok(url, [(pu_key(db, "TikTok-US-01", "灯镜", True, i), m, v) for i, m, v in CELLS])
    tot = next(r for r in g["rows"] if r["key"] == "total|revenue_cny")["values"]
    assert (tot["2027-04"], tot["2027-03"]) == ("350,000.00", "180,000.00")
    assert "超出新渠道放量规则" in g["flags"]["total|revenue_cny::2027-04"]
    assert not any(k.endswith("::2027-03") for k in g["flags"])
    r = client.post(f"{url}/submit")
    assert r.status_code == 422 and r.json()["details"]["months"] == ["2027-04"] and "2027-04" in r.json()["message"]
    r = client.put(f"{url}/over-limit-reasons", json={"reasons": {"2027-04": "4 月 TikTok 大促报名已确认，达人合作已签约"}})
    assert r.status_code == 200, r.text
    r = client.post(f"{url}/submit")
    assert r.status_code == 200 and r.json()["status_label"] == "已提交"
