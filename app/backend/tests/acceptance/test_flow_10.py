"""FLOW-10 验收（API 层，可控时钟，真实路由 + 数据库 + 钉钉替身）：期望值逐字取自 TDD验收契约 FLOW-10。

在 FLOW-09 的 24 个单位中让 6 个已提交、3 个已通过、2 个已退回、其余未开始或填报中（均经填报 / 审核接口完成）；林晓打开任务详情
→ 看板逐单位显示五种状态之一，提交率 =（6 + 3）÷ 24 = 37.5%，工作台「编制任务提交率」同为 37.5%；
时钟推进到 2026-12-21 09:00 触发逾期任务 → 只向状态不是已提交或已通过的 15 个单位的填报人及其部门负责人各发一条逾期提醒，
已提交与已通过单位不发；页面提示已发送逾期提醒的单位数 15。
"""
from datetime import datetime

from sqlalchemy import select

from app.core.clock import TZ, clock
from app.dingtalk.scheduler import run_overdue_check
from app.models import FillingUnit, User
from tests.acceptance.e1_helpers import DEADLINE, People, flow09_master, messages

FIVE = {"未开始", "填报中", "已提交", "已退回", "已通过"}


def _touch(c, unit_id):
    """填报人在可编辑单元格保存一次（任一输入行的 2027-01）。"""
    g = c.get(f"/api/filling-units/{unit_id}/grid").json()
    row = next(r for r in g["rows"] if r.get("kind") == "input" and "2027-01" not in (r.get("readonly_fields") or []))
    r = c.patch(f"/api/filling-units/{unit_id}/cells",
                json=[{"row_key": row["key"], "field": "2027-01", "value": "1", "base": row["values"].get("2027-01")}])
    assert r.status_code == 200 and r.json()["errors"] == [], r.text


def test_flow_10(seeded, dingtalk, stub, tmp_path):
    db = seeded
    flow09_master(db)
    clock.set_now(datetime(2026, 11, 2, 10, 0, tzinfo=TZ))
    p = People(db, dingtalk, tmp_path)
    lin = p("linxiao")
    r = lin.post("/api/tasks", json={"year": 2027, "deadline": DEADLINE})
    assert r.status_code == 201, r.text
    task_id = r.json()["task"]["id"]
    units = list(db.scalars(select(FillingUnit).where(FillingUnit.task_id == task_id).order_by(FillingUnit.id)))
    assert len(units) == 24
    messages(db, dingtalk, stub)
    stub.delete("/_stub/messages")
    plan = ["submitted"] * 6 + ["approved"] * 3 + ["returned"] * 2 + ["filling"] * 4 + ["not_started"] * 9
    for u, st in zip(units, plan):
        if st == "not_started":
            continue
        filler = p(db.get(User, u.filler_id).dingtalk_userid)
        _touch(filler, u.id)
        if st == "filling":
            continue
        assert filler.post(f"/api/filling-units/{u.id}/submit").status_code == 200
        head = p(db.get(User, u.reviewer_id).dingtalk_userid)
        if st == "approved":
            assert head.post(f"/api/approvals/unit/{u.id}/approve").status_code == 200
        elif st == "returned":
            r = head.post(f"/api/approvals/unit/{u.id}/reject",
                          json={"reason": "灯镜新品 10–12 月平均销量较 2026 同期高 40%，请补充依据"})
            assert r.status_code == 200, r.text
    messages(db, dingtalk, stub)
    stub.delete("/_stub/messages")

    prog = lin.get(f"/api/tasks/{task_id}/progress").json()
    assert len(prog["units"]) == 24 and {u["status_label"] for u in prog["units"]} <= FIVE
    assert prog["counts"] == {"not_started": 9, "filling": 4, "submitted": 6, "returned": 2, "approved": 3}
    assert prog["submit_rate"] in ("37.5", "37.50")
    wb = lin.get("/api/workbench").json()
    assert str(wb["key_metrics"]["submit"]["rate"]).rstrip("%") in ("37.5", "37.50"), wb["key_metrics"]["submit"]

    # 2026-12-21 08:59 尚未提醒；09:00 触发逾期任务
    run_overdue_check(db, datetime(2026, 12, 21, 8, 59, tzinfo=TZ))
    assert messages(db, dingtalk, stub) == []
    now = datetime(2026, 12, 21, 9, 0, tzinfo=TZ)
    clock.set_now(now)
    run_overdue_check(db, now)
    msgs = messages(db, dingtalk, stub)
    late = [u for u in units if db.get(FillingUnit, u.id).status not in ("submitted", "approved")]
    assert len(late) == 15 and len(msgs) == 15
    expected = sorted(sorted({db.get(User, u.filler_id).dingtalk_userid, db.get(User, u.reviewer_id).dingtalk_userid})
                      for u in late)
    assert sorted(sorted(m["userid_list"]) for m in msgs) == expected
    done = {db.get(User, u.filler_id).dingtalk_userid for u in units if u not in late}
    late_fillers = {db.get(User, u.filler_id).dingtalk_userid for u in late}
    for userid in done - late_fillers:
        assert all(userid not in m["userid_list"] for m in msgs), userid
    for m in msgs:
        assert "逾期" in m["msg"]["link"]["title"]
    run_overdue_check(db, now)
    assert messages(db, dingtalk, stub) == msgs  # 不重复提醒

    p.reset()
    prog = p("linxiao").get(f"/api/tasks/{task_id}/progress").json()
    assert prog["deadline_passed"] is True and prog["overdue_notified_count"] == 15
    reminded = [u for u in prog["units"] if u["reminded"]]
    assert len(reminded) == 15 and all(u["status"] not in ("submitted", "approved") for u in reminded)
