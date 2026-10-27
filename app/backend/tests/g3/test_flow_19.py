"""FLOW-19 季度目标调整（4A：单位两级审核 + CEO 整次终审）（AC-F08-01~04、NFR-004、DEC-022）。

期望值逐字取自 TDD验收契约.md FLOW-19 行。单元格保存（PATCH /filling-units/{id}/cells）属 G2 填报表格，
本测试直接调用其应调用的调整服务校验 ensure_month_adjustable()，提交走本组提供的提交接口。
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.core.errors import ValidationFailed
from app.models import AuditLog, FillingUnit, NotificationOutbox, PlatformUnit, TargetAdjustment
from app.models.enums import AdjustmentStatus, UnitStatus, VersionType
from app.services import adjustments
from app.services.versions import ensure_version_editable

REASON = "Prime Day 提前至 6 月，7 月部分销量前移至 6 月"


def _unit_values(db, version_id):
    return [(u.store_id, u.month, u.revenue_cny, u.gross_profit) for u in db.scalars(
        select(PlatformUnit).where(PlatformUnit.version_id == version_id).order_by(PlatformUnit.id))]


def setup_v1_v2(g3):
    stores = {"Amazon-US-01": {m: (600000, 150000) for m in range(1, 13)},
              "Wayfair-US-01": {m: (300000, 60000) for m in range(1, 13)}}
    v1 = g3.make_version(stores=stores, depts={"人力资源部": 1200000})
    g3.set_now("2027-03-15 10:00")
    stores2 = {**stores, "Wayfair-US-01": {m: (250000, 50000) for m in range(1, 13)}}
    v2 = g3.make_version(vtype=VersionType.ADJUSTED_TARGET, version_no=2, quarter=1, stores=stores2,
                         depts={"人力资源部": 1200000}, approved_at="2027-03-15 10:00", reason="Q1 下调 Wayfair")
    g3.db.add(TargetAdjustment(year=2027, quarter=1, status=AdjustmentStatus.EFFECTIVE, draft_version_id=v2.id,
                               result_version_id=v2.id, initiated_by=g3.user("林晓").id,
                               effective_at=v2.approved_at))
    g3.db.flush()
    return v1, v2


def test_flow_19_quarter_adjustment(g3):
    db = g3.db
    g3.set_now("2027-01-05 09:00")
    v1, v2 = setup_v1_v2(g3)
    g3.fake_kingdee_months(["2027-01", "2027-02", "2027-03", "2027-04"])   # 金蝶实际已导入至 2027-04
    before_v1, before_v2 = _unit_values(db, v1.id), _unit_values(db, v2.id)

    g3.set_now("2027-05-12 09:00")
    page = g3.client("林晓").get("/api/versions").json()
    assert page["actual_through"] == "2027-04" and page["actions"]["adjust"]["enabled"] is True
    assert page["adjustable_months"] == [f"2027-{m:02d}" for m in range(5, 13)]
    r = g3.client("林晓").post("/api/versions/adjustments")
    assert r.status_code == 200, r.text
    adj = db.get(TargetAdjustment, r.json()["id"])
    units = db.scalars(select(FillingUnit).where(FillingUnit.adjustment_id == adj.id)).all()
    assert len(units) == 15 and all(u.status == UnitStatus.ADJUSTING for u in units)
    assert db.scalar(select(NotificationOutbox).where(NotificationOutbox.biz_type == "adjustment_started"))

    # 王浩在调整模式编辑：2027-04 被拒，2027-06 可保存
    wang = next(u for u in units if u.name == "Amazon-US-01")
    assert wang.filler_id == g3.user("王浩").id
    with pytest.raises(ValidationFailed) as e:
        adjustments.ensure_month_adjustable(db, wang, date(2027, 4, 1))
    assert e.value.message == "该月已导入实际，不能调整"
    adjustments.ensure_month_adjustable(db, wang, date(2027, 6, 1))
    ensure_version_editable(db, adj.draft_version_id)
    june = db.scalar(select(PlatformUnit).where(PlatformUnit.version_id == adj.draft_version_id,
                                                PlatformUnit.store_id == wang.scope_object_id,
                                                PlatformUnit.month == date(2027, 6, 1)))
    june.revenue_cny, june.gross_profit = 700000, 175000
    db.flush()

    # 先不填调整原因提交 → 「请填写调整原因」；再填原因提交
    c = g3.client("王浩")
    r = c.post(f"/api/versions/adjustments/units/{wang.id}/submit", json={"adjust_reason": " "})
    assert r.status_code == 422 and r.json()["message"] == "请填写调整原因"
    r = c.post(f"/api/versions/adjustments/units/{wang.id}/submit", json={"adjust_reason": REASON})
    assert r.status_code == 200 and r.json()["status"] == UnitStatus.SUBMITTED
    for u in units:
        if u.id != wang.id:
            adjustments.submit_unit(db, g3.actor(db.get(type(g3.user("林晓")), u.filler_id).name), u.id, "同步调整")

    # 每个单位：部门负责人 → 财务负责人
    zhao = adjustments.pending_items(db, g3.actor("赵磊"))
    assert {i["type"] for i in zhao} == {"adjustment-unit"} and len(zhao) == 10
    for u in units:
        db.refresh(u)
        reviewer = db.get(type(g3.user("林晓")), u.reviewer_id).name
        adjustments.approve(db, g3.actor(reviewer), u.id, "adjustment-unit")
    assert all(db.get(FillingUnit, u.id).status == UnitStatus.DEPT_APPROVED for u in units)
    fin = adjustments.pending_items(db, g3.actor("林晓"))
    assert len([i for i in fin if i["type"] == "adjustment-unit"]) == 15
    for u in units:
        adjustments.approve(db, g3.actor("林晓"), u.id, "adjustment-unit")
    db.refresh(adj)
    assert adj.status == AdjustmentStatus.PENDING_CEO
    ceo_items = adjustments.pending_items(db, g3.actor("周明远"))
    assert [(i["type"], i["id"]) for i in ceo_items] == [("adjustment", adj.id)]

    # CEO 整次通过 → 调整后目标 V3
    g3.set_now("2027-05-12 16:30")
    result = adjustments.approve(db, g3.actor("周明远"), adj.id)
    assert result["version"] == "V3"
    db.commit()
    page = g3.client("林晓").get("/api/versions").json()
    v3 = next(v for v in page["versions"] if v["label"] == "V3")
    assert (v3["type_label"], v3["approver"], v3["time"], v3["status_label"]) == \
        ("调整后目标", "周明远（CEO 审批）", "2027-05-12 16:30", "当前目标")
    assert REASON in v3["reason"]
    assert next(v for v in page["versions"] if v["label"] == "V2")["status_label"] == "已被 V3 替代"
    # V1 与 V2 全部单元值与调整前逐值相同
    assert _unit_values(db, v1.id) == before_v1 and _unit_values(db, v2.id) == before_v2

    # 同一季度再次发起被阻止，按钮显示不可用原因
    r = g3.client("林晓").post("/api/versions/adjustments")
    assert r.status_code == 409
    expected = "本季度已有一次经 CEO 审批通过的目标调整（V3，2027-05-12），2027-07-01 起可发起下季度调整"
    assert r.json()["message"] == expected
    actions = g3.client("林晓").get("/api/versions").json()["actions"]["adjust"]
    assert actions == {"enabled": False, "reason": expected}

    # NFR-004：发起、提交、各级审批、生效均有审计
    acts = set(db.scalars(select(AuditLog.action)))
    assert {"adjustment_started", "adjustment_unit_submitted", "adjustment_unit_approved",
            "adjustment_pending_ceo", "adjustment_effective"} <= acts


def test_flow_19_in_progress_blocks_and_ceo_return(g3):
    db = g3.db
    g3.set_now("2027-01-05 09:00")
    setup_v1_v2(g3)
    g3.set_now("2027-05-12 09:00")
    assert g3.client("林晓").post("/api/versions/adjustments").status_code == 200
    r = g3.client("林晓").post("/api/versions/adjustments")
    assert r.status_code == 409 and "审批结束前不能再发起" in r.json()["message"]
    # 非财务负责人不能发起
    assert g3.client("陈思雨").post("/api/versions/adjustments").status_code == 403
    # 退回原因必填
    unit = db.scalar(select(FillingUnit).where(FillingUnit.name == "Amazon-US-01"))
    adjustments.submit_unit(db, g3.actor("王浩"), unit.id, "补充 6 月促销")
    with pytest.raises(ValidationFailed) as e:
        adjustments.reject(db, g3.actor("赵磊"), unit.id, "", "adjustment-unit")
    assert e.value.message == "请填写退回原因"
    adjustments.reject(db, g3.actor("赵磊"), unit.id, "6 月销量依据不足", "adjustment-unit")
    assert db.get(FillingUnit, unit.id).status == UnitStatus.RETURNED
