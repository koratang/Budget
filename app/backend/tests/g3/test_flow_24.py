"""FLOW-24 BI 与金蝶收入核对（AC-F09-07、AC-F02-08）。期望值逐字取自 TDD验收契约.md FLOW-24 行。"""
from datetime import date
from decimal import Decimal

from app.models import FxActual
from app.services import importer
from tests.g3.fixtures_g3 import fixture_path


def test_flow_24_reconciliation(g3):
    db = g3.db
    g3.add_skus()
    g3.set_now("2027-05-20 10:00")
    db.add(FxActual(month=date(2027, 4, 1), currency="USD", rate=Decimal("7.2000")))  # GBP 未录入
    db.flush()
    g3.import_file(fixture_path("BI_2027-04_销售明细.xlsx"), "bi")
    g3.import_file(fixture_path("金蝶_2027-04_利润表_v3.xlsx"), "kingdee")

    # 单元：核对计算
    data = importer.reconciliation(db, date(2027, 4, 1))
    rows = {r["store"]: r for r in data["rows"]}
    us = rows["Amazon-US-01"]
    assert (us["bi_local_display"], us["bi_cny"], us["kingdee"]) == ("$ 77,000.00 USD", "554400", "535000")
    assert us["diff_rate_display"] == "+3.63%" and us["over"] is True
    wf = rows["Wayfair-US-01"]
    assert (wf["bi_cny"], wf["kingdee"], wf["diff_rate_display"], wf["over"]) == ("360000", "355000", "+1.41%", False)
    uk = rows["Amazon-UK-01"]
    assert uk["bi_cny"] is None and uk["diff_rate"] is None and uk["counted"] is False
    assert "缺少 2027-04 汇率" in uk["note"]

    # 接口：「只看差异率超过 3%」只留 Amazon-US-01
    r = g3.client("陈思雨").get("/api/reconciliation", params={"month": "2027-04", "over_only": "true"})
    assert r.status_code == 200
    assert [x["store"] for x in r.json()["rows"]] == ["Amazon-US-01"]
    assert r.json()["kpis"]["over"] == 1
    assert {x["currency"]: x["rate"] for x in r.json()["rates"]} == {"USD": "7.2000"}
    # 无权限角色
    assert g3.client("王浩").get("/api/reconciliation", params={"month": "2027-04"}).status_code == 403
