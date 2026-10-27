"""RULE-06 版本锁定（AC-F07-05、AC-F08-04、AC-F08-07、AC-F02-11；DEC-016、DEC-020）。期望值逐字取自 TDD验收契约.md：

接口修改全部被拒且数值不变；数据库触发器拒绝对锁定版本单元与锁定年度预算汇率的 UPDATE、DELETE；锁定版本只能通过新版本
（调整或快照）演进。

版本经真实接口产生：年初原始目标 V1 = 编制任务经 CEO 通过并锁定；V2 为 2027 Q1 已生效调整（前置）；调整后目标 V3 =
2027 Q2 调整经单位两级审核 + CEO 终审生效；Q2 快照 = 滚动预测发布。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from app.models import BudgetVersion, FillingUnit, PlatformUnit, TargetAdjustment, User
from app.models.enums import AdjustmentStatus, VersionType
from tests.g2.helpers import minimal_units
from tests.g2.test_smoke_03 import _cells
from tests.g3.conftest import G3

@pytest.fixture
def g3(seeded, dingtalk, tmp_path):
    return G3(seeded, dingtalk, tmp_path)


def build_versions(g: G3) -> dict:
    db = g.db
    g.set_now("2026-12-01 09:00")
    r = g.client("林晓").post("/api/tasks", json={"year": 2027, "deadline": "2026-12-20", "units": minimal_units(db)})
    assert r.status_code == 201, r.text
    task_id = r.json()["task"]["id"]
    for name, (filler, head, cell) in _cells(db).items():
        unit = db.scalar(select(FillingUnit).where(FillingUnit.task_id == task_id, FillingUnit.name == name))
        fname, hname = (db.scalar(select(User.name).where(User.dingtalk_userid == x)) for x in (filler, head))
        c = g.client(fname)
        g_ = c.get(f"/api/filling-units/{unit.id}/grid").json()
        base = next((row["values"].get(cell[1]) for row in g_["rows"] if row["key"] == cell[0]), None)
        r = c.patch(f"/api/filling-units/{unit.id}/cells",
                    json=[{"row_key": cell[0], "field": cell[1], "value": cell[2], "base": base}])
        assert r.status_code == 200 and r.json()["errors"] == [], r.text
        assert c.post(f"/api/filling-units/{unit.id}/submit").status_code == 200
        assert g.client(hname).post(f"/api/approvals/unit/{unit.id}/approve").status_code == 200
    assert g.client("林晓").post(f"/api/tasks/{task_id}/submit-to-ceo").status_code == 200
    g.set_now("2026-12-28 17:30")
    assert g.client("周明远").post(f"/api/approvals/task/{task_id}/approve").json()["status"] == "completed"
    v1 = db.scalar(select(BudgetVersion).where(BudgetVersion.type == VersionType.ORIGINAL_TARGET))
    v1_unit = db.scalar(select(FillingUnit).where(FillingUnit.task_id == task_id, FillingUnit.name == "Amazon-US-01"))

    # 前置：2027 Q1 已生效调整 V2
    g.set_now("2027-03-15 10:00")
    stores = {"Amazon-US-01": {m: (600000, 150000) for m in range(1, 13)}}
    v2 = g.make_version(vtype=VersionType.ADJUSTED_TARGET, version_no=2, quarter=1, stores=stores,
                        approved_at="2027-03-15 10:00", reason="Q1 调整")
    db.add(TargetAdjustment(year=2027, quarter=1, status=AdjustmentStatus.EFFECTIVE, draft_version_id=v2.id,
                            result_version_id=v2.id, initiated_by=g.user("林晓").id, effective_at=v2.approved_at))
    db.flush()

    # 2027 Q2 调整 → V3
    g.set_now("2027-05-12 09:00")
    g.fake_kingdee_months(["2027-01", "2027-02", "2027-03", "2027-04"])
    r = g.client("林晓").post("/api/versions/adjustments")
    assert r.status_code == 200, r.text
    adj_id = r.json()["id"]
    units = db.scalars(select(FillingUnit).where(FillingUnit.adjustment_id == adj_id)).all()
    for u in units:
        r = g.client(db.get(User, u.filler_id).name).post(f"/api/versions/adjustments/units/{u.id}/submit",
                                                          json={"adjust_reason": "Prime Day 提前至 6 月"})
        assert r.status_code == 200, r.text
    for u in units:
        assert g.client(db.get(User, u.reviewer_id).name).post(
            f"/api/approvals/adjustment-unit/{u.id}/approve").status_code == 200
    for u in units:
        assert g.client("林晓").post(f"/api/approvals/adjustment-unit/{u.id}/approve").status_code == 200
    r = g.client("周明远").post(f"/api/approvals/adjustment/{adj_id}/approve")
    assert r.status_code == 200 and r.json()["version"] == "V3", r.text
    adj = db.get(TargetAdjustment, adj_id)
    v3 = db.get(BudgetVersion, adj.result_version_id)
    v3_unit = next(u for u in units if u.name == "Amazon-US-01")

    # Q2 滚动预测发布为快照
    g.set_now("2027-05-20 10:00")
    r = g.client("林晓").post("/api/versions/rolling")
    assert r.status_code == 200, r.text
    rolling_id = r.json()["id"]
    r = g.client("林晓").post(f"/api/versions/rolling/{rolling_id}/publish", json={"confirm_unsubmitted": True})
    assert r.status_code == 200, r.text
    q2 = db.get(BudgetVersion, r.json()["id"])
    assert q2.type == VersionType.SNAPSHOT and q2.quarter == 2
    return {"v1": v1, "v3": v3, "q2": q2, "v1_unit": v1_unit, "v3_unit": v3_unit}


def _rows(db, vid):
    db.expire_all()
    return [(u.id, u.spu_count, u.avg_sales, u.avg_price, u.revenue_cny, u.gross_profit)
            for u in db.scalars(select(PlatformUnit).where(PlatformUnit.version_id == vid).order_by(PlatformUnit.id))]


def test_rule_06_locked_versions_reject_api_and_db(g3):
    db = g3.db
    w = build_versions(g3)
    v1, v3, q2 = w["v1"], w["v3"], w["q2"]
    for v in (v1, v3, q2):
        db.refresh(v)
        assert v.locked, v.name
    before = {k: _rows(db, w[k].id) for k in ("v1", "v3", "q2")}
    assert all(before.values())

    # 接口修改：V1 编制单位、V3 调整单位、Q2 快照（滚动表格）
    wang = g3.client("王浩")
    us = g3.store("Amazon-US-01")
    cat = g3.category("浴室柜").id
    results = []
    for label, url, month in (("V1", f"/api/filling-units/{w['v1_unit'].id}", "2027-03"),
                              ("V3", f"/api/filling-units/{w['v3_unit'].id}", "2027-06"),
                              ("Q2 快照", f"/api/filling-units/rolling/{q2.id}/platform:{us.id}", "2027-06")):
        g_ = wang.get(f"{url}/grid")
        key = next((r["key"] for r in g_.json()["rows"] if r["key"].endswith("|spu_count")),
                   f"pu:{us.id}:{us.site_id}:{cat}:1|spu_count") if g_.status_code == 200 else \
            f"pu:{us.id}:{us.site_id}:{cat}:1|spu_count"
        r = wang.patch(f"{url}/cells", json=[{"row_key": key, "field": month, "value": "99", "base": None}])
        results.append((label, r.status_code, r.json().get("code"), r.json().get("message")))
        r2 = wang.post(f"{url}/fill-year", json={"row_key": key.replace("spu_count", "avg_price"), "value": "1"})
        results.append((label + " 填充全年", r2.status_code, r2.json().get("code"), r2.json().get("message")))
    print("\nRULE-06 接口修改：", results)
    for label, status, code, msg in results:
        assert (status, code, msg) == (409, "version_locked", "版本已锁定，不能修改"), label
    # 预算汇率：已锁定年度 2027 经接口修改被拒
    r = g3.client("陈思雨").put("/api/master/fx/budget", json={"year": 2027, "currency": "USD", "rate": "7.5000"})
    print("RULE-06 汇率接口：", r.status_code, r.json())
    assert (r.status_code, r.json()["message"]) == (409, "已随年初原始目标锁定")
    assert {k: _rows(db, w[k].id) for k in ("v1", "v3", "q2")} == before
    db.commit()

    # 数据库层：以应用数据库账号直接 UPDATE / DELETE（触发器拒绝）
    for v in (v1, v3, q2):
        for sql, msg in ((f"UPDATE platform_unit SET spu_count = 99 WHERE version_id = {v.id}", "版本已锁定，不能修改"),
                         (f"DELETE FROM platform_unit WHERE version_id = {v.id}", "版本已锁定，不能修改")):
            with pytest.raises(Exception) as e:
                with db.begin_nested():
                    db.execute(text(sql))
            assert msg in str(e.value) and "BG001" in repr(e.value.orig.sqlstate), (sql, e.value)
    for sql in ("UPDATE fx_budget SET rate = 7.5 WHERE year = 2027 AND currency = 'USD'",
                "DELETE FROM fx_budget WHERE year = 2027 AND currency = 'USD'"):
        with pytest.raises(Exception) as e:
            with db.begin_nested():
                db.execute(text(sql))
        assert "已随年初原始目标锁定" in str(e.value) and e.value.orig.sqlstate == "BG002", sql
    assert {k: _rows(db, w[k].id) for k in ("v1", "v3", "q2")} == before

    # 锁定版本只能通过新版本演进：V1 → V2 → V3（调整）与 Q2 快照均为不同版本，V1 数值未被覆盖
    assert len({v1.id, v3.id, q2.id}) == 3 and v3.source_version_id is not None
    assert before["v1"] != before["v3"]
