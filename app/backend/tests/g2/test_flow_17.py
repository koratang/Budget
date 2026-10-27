"""FLOW-17：新渠道超放量标注与理由（AC-F13-02、DEC-023）。

契约期望：2027-04 单元标注「超出新渠道放量规则」，2027-03 不标注；未填理由时提交被阻止并指出 2027-04；
填写理由后提交成功，状态变为已提交
"""
from datetime import date

from app.models import Rule, RuleVersion, UserScope
from tests.g2.helpers import grid, login, minimal_units, publish, pu_key, row, save, store, submit, uid, unit_by_name

LIMITS = ["200000.00", "300000.00", "360000.00", "420000.00", "480000.00", "520000.00", "540000.00", "600000.00",
          "660000.00", "720000.00", "780000.00", "840000.00"]


def setup_rule_and_store(db):
    s = store(db, "TikTok-US-01")
    s.is_new_channel = True
    s.new_channel_start = date(2027, 3, 1)
    db.add(UserScope(user_id=uid(db, "wanghao"), scope_type="store", object_id=s.id))
    rule = Rule(name="新渠道月收入放量上限", type="quota_standard")
    db.add(rule)
    db.flush()
    rv = RuleVersion(rule_id=rule.id, version_no=1, credibility="unverified", status="effective",
                     content={"kind": "new_channel_ramp", "unit": "CNY/店铺/月", "limits": LIMITS})
    db.add(rv)
    db.flush()
    rule.current_version_id = rv.id
    db.flush()


def test_flow_17_new_channel_over_limit(seeded, client):
    db = seeded
    setup_rule_and_store(db)
    task_id = publish(client, db, minimal_units(db, stores=("Amazon-US-01", "TikTok-US-01"))).json()["task"]["id"]
    unit_id = unit_by_name(db, task_id, "TikTok-US-01").id
    k = lambda item: pu_key(db, "TikTok-US-01", "灯镜", True, item)  # noqa: E731
    login(client, db, "wanghao")
    # 2027-04 全部单元人民币收入合计 350,000.00（6 × 90.8 × 90.23 USD × 7.12）；2027-03 合计 180,000.00
    r = save(client, unit_id, [(k("spu_count"), "2027-04", "6"), (k("avg_sales"), "2027-04", "90.8"),
                               (k("avg_price"), "2027-04", "90.23"),
                               (k("spu_count"), "2027-03", "6"), (k("avg_sales"), "2027-03", "116.01"),
                               (k("avg_price"), "2027-03", "36.32")])
    assert r.json()["errors"] == [], r.text
    g = r.json()["grid"]
    assert row(g, "total|revenue_cny")["values"]["2027-04"] == "350,000.00"
    assert row(g, "total|revenue_cny")["values"]["2027-03"] == "180,000.00"
    assert "超出新渠道放量规则" in g["flags"]["total|revenue_cny::2027-04"]
    assert "total|revenue_cny::2027-03" not in g["flags"]
    assert [o["month"] for o in g["over_limit"]] == ["2027-04"]
    assert g["over_limit"][0]["k"] == 2 and g["over_limit"][0]["limit_display"] == "¥ 300,000.00"

    r = submit(client, unit_id)
    assert r.status_code == 422
    assert r.json()["details"]["months"] == ["2027-04"] and "2027-04" in r.json()["message"]

    r = client.put(f"/api/filling-units/{unit_id}/over-limit-reasons",
                   json={"reasons": {"2027-04": "4 月 TikTok 大促报名已确认，备货与达人合作已签约"}})
    assert r.status_code == 200, r.text
    r = submit(client, unit_id)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted"
    assert grid(client, unit_id)["unit"]["status_label"] == "已提交"
