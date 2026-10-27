"""FLOW-24 BI 与金蝶收入核对（AC-F09-07、AC-F02-08）：单元（核对计算）+ 真实路由。期望值逐字取自契约 FLOW-24。"""
from datetime import date
from decimal import Decimal

from app.models import FxActual
from app.services import importer
from tests.g3.conftest import g3  # noqa: F401
from tests.g3.fixtures_g3 import fixture_path


def setup(g3):
    g3.add_skus()
    g3.set_now("2027-05-20 10:00")
    g3.db.add(FxActual(month=date(2027, 4, 1), currency="USD", rate=Decimal("7.2000")))   # GBP 缺 2027-04
    g3.db.flush()
    g3.import_file(fixture_path("BI_2027-04_销售明细.xlsx"), "bi")       # Amazon-US-01 USD 77,000；Wayfair USD 50,000
    g3.import_file(fixture_path("金蝶_2027-04_利润表_v3.xlsx"), "kingdee")  # 金蝶收入 535,000 / 355,000


def test_flow_24_unit(g3):  # noqa: F811
    setup(g3)
    rows = {r["store"]: r for r in importer.reconciliation(g3.db, date(2027, 4, 1))["rows"]}
    us, wf, uk = rows["Amazon-US-01"], rows["Wayfair-US-01"], rows["Amazon-UK-01"]
    assert (us["bi_local_display"], us["kingdee"]) == ("$ 77,000.00 USD", "535000")
    assert Decimal(us["bi_cny"]) == Decimal("554400.00")
    assert (us["diff_rate_display"], us["over"]) == ("+3.63%", True)            # 标红
    assert Decimal(wf["bi_cny"]) == Decimal("360000.00") and Decimal(wf["kingdee"]) == Decimal("355000")
    assert (wf["diff_rate_display"], wf["over"]) == ("+1.41%", False)           # 不标红
    assert uk["bi_cny"] is None and uk["diff_rate"] is None and uk["counted"] is False
    assert "缺少 2027-04 汇率" in uk["note"]                                     # GBP 不计算并提示


def test_flow_24_api(g3):  # noqa: F811
    setup(g3)
    c = g3.client("陈思雨")
    r = c.get("/api/reconciliation", params={"month": "2027-04"})
    assert r.status_code == 200, r.text
    rows = {x["store"]: x for x in r.json()["rows"]}
    assert rows["Amazon-US-01"]["diff_rate_display"] == "+3.63%" and rows["Amazon-US-01"]["over"] is True
    assert rows["Wayfair-US-01"]["diff_rate_display"] == "+1.41%" and rows["Wayfair-US-01"]["over"] is False
    assert "缺少 2027-04 汇率" in rows["Amazon-UK-01"]["note"]
    # 「只看差异率超过 3%」只留 Amazon-US-01
    r = c.get("/api/reconciliation", params={"month": "2027-04", "over_only": "true"})
    assert [x["store"] for x in r.json()["rows"]] == ["Amazon-US-01"]
