"""FLOW-04 渠道/店铺与新渠道标记（REQ-F02-01，AC-F02-01/02/10；REQ-F13-01，AC-F13-01）：期望值逐字取自 TDD验收契约 FLOW-04。

编制任务生成平台渠道单位（G2）与实际导入校验（G3）读取主数据服务的 fillable_stores / import_store_lookup；
本测试验证这两个主数据出口，任务生成与导入入库本身由 G2、G3 的场景测试覆盖。
"""
from datetime import date

from sqlalchemy import func, select

from app.calc.periods import add_months, fmt_month
from app.models import Store
from app.services.masterdata import fillable_stores, import_store_lookup, is_new_channel_month
from tests.g1.helpers import channel_id, login, site_id, store_id


def _store_row(client, name, month):
    data = client.get("/api/master/stores", params={"month": month}).json()
    return next(s for s in data["stores"] if s["name"] == name), data


def test_new_store_available_and_duplicate_rejected(seeded, db, dingtalk):
    bp = login(db, dingtalk, "chensiyu")
    body = {"channel_id": channel_id(db, "Wayfair"), "name": "Wayfair-CA-01", "site_id": site_id(db, "CA"),
            "currency": "CAD", "is_active": True}
    r = bp.post("/api/master/stores", json=body)
    assert r.status_code == 201, r.text
    assert "Wayfair-CA-01" in [s.name for s in fillable_stores(db)]
    assert "Wayfair-CA-01" in import_store_lookup(db)
    row, _ = _store_row(bp, "Wayfair-CA-01", "2027-01")
    assert (row["channel_name"], row["site_name"], row["currency"]) == ("Wayfair", "加拿大", "CAD")

    before = db.scalar(select(func.count()).select_from(Store))
    r = bp.post("/api/master/stores", json=body)
    assert r.status_code == 422 and r.json()["message"] == "店铺名称已存在"
    assert db.scalar(select(func.count()).select_from(Store)) == before


def test_disabled_store_not_in_new_filling_but_import_accepts(seeded, db, dingtalk):
    bp = login(db, dingtalk, "chensiyu")
    sid = store_id(db, "Lowes-US-02")
    s = db.get(Store, sid)
    r = bp.put(f"/api/master/stores/{sid}", json={"channel_id": s.channel_id, "name": s.name, "site_id": s.site_id,
                                                  "currency": s.currency, "is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert "Lowes-US-02" not in [x.name for x in fillable_stores(db)]
    assert import_store_lookup(db)["Lowes-US-02"] == (sid, s.site_id)


def test_new_channel_mark_for_12_months(seeded, db, dingtalk):
    head = login(db, dingtalk, "linxiao")
    bp = login(db, dingtalk, "chensiyu")
    sid = store_id(db, "TikTok-US-01")
    assert bp.get("/api/master/stores").json()["can_mark_new_channel"] is False
    r = bp.put(f"/api/master/stores/{sid}/new-channel", json={"is_new": True, "start": "2027-03"})
    assert r.status_code == 403 and r.json()["message"] == "无权限"

    r = head.put(f"/api/master/stores/{sid}/new-channel", json={"is_new": True, "start": "2027-03"})
    assert r.status_code == 200, r.text
    assert head.get("/api/master/stores").json()["can_mark_new_channel"] is True
    for k in range(12):
        month = fmt_month(add_months(date(2027, 3, 1), k))   # 2027-03 … 2028-02
        row, _ = _store_row(head, "TikTok-US-01", month)
        assert row["new_channel"]["is_new"] is True, month
        assert is_new_channel_month(db, db.get(Store, sid), add_months(date(2027, 3, 1), k))
    row, _ = _store_row(head, "TikTok-US-01", "2028-03")
    assert row["new_channel"]["is_new"] is False and row["new_channel"]["status"] == "expired"
    assert row["new_channel"]["end"] == "2028-02"
    assert not is_new_channel_month(db, db.get(Store, sid), date(2028, 3, 1))
