"""FLOW-10：进度看板与逾期提醒（可控时钟）。

契约期望：看板逐单位显示五种状态之一，提交率 =（6 + 3）÷ 24 = 37.5%，工作台「编制任务提交率」同为 37.5%；
09:00 只向状态不是已提交或已通过的 15 个单位的填报人及其部门负责人各发一条逾期提醒，已提交与已通过单位不发；
页面提示已发送逾期提醒的单位数 15。
"""
from datetime import datetime

from sqlalchemy import select

from app.core.clock import TZ, clock
from app.dingtalk.scheduler import run_overdue_check
from app.models import FillingUnit, NotificationOutbox, User
from tests.g2.helpers import login, publish
from tests.g2.test_flow_09 import setup_flow09

FIVE_STATES = {"not_started", "filling", "submitted", "returned", "approved"}


def test_flow_10_progress_rate_and_overdue(seeded, client):
    db = seeded
    setup_flow09(db)
    task_id = publish(client, db).json()["task"]["id"]
    units = list(db.scalars(select(FillingUnit).where(FillingUnit.task_id == task_id).order_by(FillingUnit.id)))
    assert len(units) == 24
    plan = ["submitted"] * 6 + ["approved"] * 3 + ["returned"] * 2 + ["filling"] * 4 + ["not_started"] * 9
    for u, st in zip(units, plan):
        u.status = st
        if st == "returned":
            u.return_reason = "灯镜新品 10–12 月平均销量较 2026 同期高 40%"
    db.flush()

    login(client, db, "linxiao")
    p = client.get(f"/api/tasks/{task_id}/progress").json()
    assert {u["status"] for u in p["units"]} <= FIVE_STATES and len(p["units"]) == 24
    assert p["submit_rate"] == "37.5"  # （6 + 3）÷ 24 = 37.5%
    wb = client.get("/api/workbench")
    if wb.status_code == 200:  # 工作台由 G4 实现：同一口径
        submit = wb.json().get("key_metrics", {}).get("submit") or {}
        assert str(submit.get("rate", "")).rstrip("%") in ("37.5", "37.50"), submit

    # 截止次日 09:00 之前不提醒
    run_overdue_check(db, datetime(2026, 12, 21, 8, 59, tzinfo=TZ))
    assert db.scalars(select(NotificationOutbox).where(NotificationOutbox.biz_type == "task_overdue")).all() == []

    now = datetime(2026, 12, 21, 9, 0, tzinfo=TZ)
    clock.set_now(now)
    run_overdue_check(db, now)
    rows = db.scalars(select(NotificationOutbox).where(NotificationOutbox.biz_type == "task_overdue")).all()
    late = [u for u in units if u.status not in ("submitted", "approved")]
    assert len(late) == 15 and len(rows) == 15
    assert {r.biz_id for r in rows} == {u.id for u in late}
    for r in rows:
        u = db.get(FillingUnit, r.biz_id)
        expected = {db.get(User, u.filler_id).dingtalk_userid, db.get(User, u.reviewer_id).dingtalk_userid}
        assert set(r.receivers) == expected  # 填报人及其部门负责人各一条（同一条工作通知的两位接收人）
    # 再次触发不重复提醒
    run_overdue_check(db, now)
    assert len(db.scalars(select(NotificationOutbox).where(NotificationOutbox.biz_type == "task_overdue")).all()) == 15

    login(client, db, "linxiao")  # 时钟推进后旧会话已超 8 小时
    r = client.get(f"/api/tasks/{task_id}/progress")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["overdue_notified_count"] == 15
    assert p["deadline_passed"] is True
    reminded = [u for u in p["units"] if u["reminded"]]
    assert len(reminded) == 15 and all(u["status"] not in ("submitted", "approved") for u in reminded)
