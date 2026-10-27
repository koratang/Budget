"""FLOW-28 验收（真实路由 + 权限 + 数据库）：偏差说明：财务BP 填写，有查看权限的角色在对应报告行看到说明、填写人与填写时间。

期望值逐字取自 TDD验收契约.md FLOW-28 行。
"""
from datetime import datetime

from sqlalchemy import select

from app.core.clock import clock
from app.models import AuditLog, Category, Department
from app.models.enums import VersionType

from tests.g4 import builders as B
from tests.acceptance.e3_scenarios import flow28

CHANNEL_NOTE = "4 月中旬断货 12 天，补货 4-28 到仓"
CATEGORY_NOTE = "3 款框镜因包装认证延期上架"
DEPT_NOTE = "4 月 KBIS 展会一次性支付"


def test_variance_notes(client, seeded):
    db = seeded
    flow28(db)
    clock.set_now(datetime(2027, 5, 12, 10, 30))
    us = B.store(db, "Amazon-US-01")
    frame = db.scalar(select(Category).where(Category.name == "框镜"))
    market = db.scalar(select(Department).where(Department.name == "市场部"))
    expo = B.account(db, "展会费")

    B.login(client, db, "chensiyu")
    dept_report = client.get("/api/reports/dept-expense", params={"year": 2027}).json()
    assert dept_report["can_edit_note"] is True
    payloads = [
        {"report_type": "channel-site", "month": "2027-04", "object_type": "store", "object_key": str(us.id),
         "note": CHANNEL_NOTE},
        {"report_type": "category", "month": "2027-04", "object_type": "category", "object_key": f"{frame.id}:new",
         "note": CATEGORY_NOTE},
        {"report_type": "dept-expense", "month": dept_report["through"], "object_type": "dept-account",
         "object_key": f"{market.id}:{expo.id}", "note": DEPT_NOTE},
    ]
    for p in payloads:
        r = client.put("/api/variance-notes", json=p)
        assert r.status_code == 200, r.text
        assert r.json()["author"] == "陈思雨" and r.json()["updated_at"] == "2027-05-12 10:30"
    # 空内容保存提示「请填写说明内容」
    r = client.put("/api/variance-notes", json={**payloads[0], "note": "  "})
    assert r.status_code == 422 and r.json()["message"] == "请填写说明内容"
    # 修改记录进入审计日志
    assert db.scalar(select(AuditLog).where(AuditLog.action == "variance_note.save").limit(1)) is not None

    def channel_note(userid):
        B.login(client, db, userid)
        data = client.get("/api/reports/channel-site", params={"month": "2027-04"}).json()
        return next(r for r in data["rows"] if r["name"] == "Amazon-US-01")["note"], data["can_edit_note"]

    def category_note(userid):
        B.login(client, db, userid)
        data = client.get("/api/reports/category", params={"month": "2027-04"}).json()
        g = next(g for g in data["groups"] if g["category"] == "框镜")
        return next(r for r in g["rows"] if r["kind"] == "新品")["note"]

    def dept_note(userid):
        B.login(client, db, userid)
        data = client.get("/api/reports/dept-expense", params={"year": 2027}).json()
        g = next(g for g in data["groups"] if g["department"] == "市场部")
        return next(r for r in g["rows"] if r["account"] == "展会费")["note"]

    expected = {"author": "陈思雨", "updated_at": "2027-05-12 10:30"}
    for userid in ("wanghao", "linxiao", "zhoumingyuan"):
        note, can_edit = channel_note(userid)
        assert note == {"text": CHANNEL_NOTE, **expected}
        assert can_edit is False  # 王浩、林晓、周明远都没有「填写说明」入口
        assert category_note(userid) == {"text": CATEGORY_NOTE, **expected}
    for userid in ("linxiao", "zhoumingyuan"):
        assert dept_note(userid) == {"text": DEPT_NOTE, **expected}

    # 王浩无「填写说明」入口，调用保存接口返回 403
    B.login(client, db, "wanghao")
    r = client.put("/api/variance-notes", json={**payloads[0], "note": "王浩尝试修改"})
    assert r.status_code == 403 and r.json() == {"code": "forbidden", "message": "无权限"}


def test_note_requires_known_report(client, seeded):
    db = seeded
    B.version(db, 2027, VersionType.ORIGINAL_TARGET, "V1 年初原始目标")
    B.login(client, db, "chensiyu")
    r = client.put("/api/variance-notes", json={"report_type": "unknown", "month": "2027-04",
                                                "object_type": "store", "object_key": "1", "note": "说明"})
    assert r.status_code == 422
