"""G2 填报表格与 G3 版本能力的对接点（AC-F08-02/03/05）：
- 调整单位保存：已导入金蝶实际的月份由 adjustments.ensure_month_adjustable 拒绝「该月已导入实际，不能调整」；
- 调整单位提交：走 adjustments.submit_unit，调整原因必填「请填写调整原因」；
- 滚动预测稿：按 versions.open_months 只开放本季度及以后月份，用同一表格编辑并经 versions.submit_rolling_unit 提交。
"""
from datetime import date

from sqlalchemy import insert, select

from app.calc.periods import year_months
from app.models import (BudgetVersion, Category, FillingUnit, ImportBatch, PlatformUnit, Store, TargetAdjustment)
from tests.g2.helpers import grid, login, pu_key, row, save, store, uid


def _platform_rows(db, version_id: int, store_name: str = "Amazon-US-01") -> None:
    s = db.scalar(select(Store).where(Store.name == store_name))
    cats = list(db.scalars(select(Category.id)))
    db.execute(insert(PlatformUnit), [dict(version_id=version_id, month=m, channel_id=s.channel_id, store_id=s.id,
                                            site_id=s.site_id, category_id=c, is_new=n)
                                       for m in year_months(2027) for c in cats for n in (True, False)])


def _actuals_through_april(db) -> None:
    for m in range(1, 5):
        db.add(ImportBatch(source="kingdee", period=date(2027, m, 1), file_name=f"金蝶_2027-{m:02d}_利润表.xlsx",
                           status="effective", uploaded_by=uid(db, "chensiyu")))
    db.flush()


def test_adjustment_unit_months_and_reason(seeded, client):
    db = seeded
    v = BudgetVersion(year=2027, type="adjustment_draft", version_no=1, name="2027 年第二季度调整稿")
    db.add(v)
    db.flush()
    _platform_rows(db, v.id)
    adj = TargetAdjustment(year=2027, quarter=2, status="in_progress", draft_version_id=v.id)
    db.add(adj)
    db.flush()
    unit = FillingUnit(adjustment_id=adj.id, version_id=v.id, unit_type="platform",
                       scope_object_id=store(db, "Amazon-US-01").id, name="Amazon-US-01",
                       filler_id=uid(db, "wanghao"), reviewer_id=uid(db, "zhaolei"), status="adjusting")
    db.add(unit)
    _actuals_through_april(db)
    login(client, db, "wanghao")
    key = pu_key(db, "Amazon-US-01", "框镜", False, "avg_sales")
    g = grid(client, unit.id)
    assert "2027-04" in row(g, key)["readonly_fields"] and "2027-06" not in row(g, key)["readonly_fields"]
    r = save(client, unit.id, [(key, "2027-04", "60"), (key, "2027-06", "70")], g)
    errs = r.json()["errors"]
    assert [(e["field"], e["message"]) for e in errs] == [("2027-04", "该月已导入实际，不能调整")]
    assert row(r.json()["grid"], key)["values"]["2027-06"] == "70.0"
    r = client.post(f"/api/filling-units/{unit.id}/submit", json={})
    assert r.status_code == 422 and r.json()["message"] == "请填写调整原因"
    r = client.post(f"/api/filling-units/{unit.id}/submit",
                    json={"adjust_reason": "Prime Day 提前至 6 月，7 月部分销量前移至 6 月"})
    assert r.status_code == 200 and r.json()["status"] == "submitted"


def test_rolling_forecast_edit_and_submit(seeded, client):
    db = seeded
    v = BudgetVersion(year=2027, type="rolling_draft", version_no=2, quarter=2, name="2027 Q2 滚动预测稿")
    db.add(v)
    db.flush()
    _platform_rows(db, v.id)
    login(client, db, "wanghao")
    mine = client.get("/api/filling-units?mine=1").json()["items"]
    item = next(m for m in mine if m["rolling"])
    assert item["rolling"]["version_id"] == v.id and item["name"] == "Amazon-US-01" and item["editable"]
    base = f"/api/filling-units/rolling/{v.id}/{item['rolling']['key']}"
    g = client.get(f"{base}/grid").json()
    key = pu_key(db, "Amazon-US-01", "灯镜", True, "spu_count")
    assert {"2027-01", "2027-02", "2027-03"} <= set(row(g, key)["readonly_fields"])
    assert "2027-04" not in row(g, key)["readonly_fields"]
    body = [{"row_key": key, "field": "2027-02", "value": "8", "base": "0"},
            {"row_key": key, "field": "2027-05", "value": "9", "base": "0"}]
    r = client.patch(f"{base}/cells", json=body)
    assert r.status_code == 200, r.text
    assert [(e["field"], e["code"]) for e in r.json()["errors"]] == [("2027-02", "month_locked")]
    assert row(r.json()["grid"], key)["values"]["2027-05"] == "9"
    r = client.post(f"{base}/submit")
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    r = client.patch(f"{base}/cells", json=[{"row_key": key, "field": "2027-06", "value": "1", "base": "0"}])
    assert r.status_code == 409 and r.json()["message"] == "已提交，退回后才能修改"
