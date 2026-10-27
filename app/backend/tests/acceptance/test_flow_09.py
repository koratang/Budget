"""FLOW-09 验收（API 层，真实路由 + 数据库 + 钉钉替身）：期望值逐字取自 TDD验收契约 FLOW-09。

种子 5 个启用店铺 + 1 个停用店铺、美国业务部与外贸部各有启用客户、15 个参与部门；林晓发布「2027 年度预算编制」（截止 2026-12-20）
→ 24 个填报单位：平台渠道 5、B 端 2、成本比例 1、物流比例 1、部门费用 15，各单位出现在对应填报人的「我的填报」；
每个单位填报人收到 1 条工作通知，含「2027」「2026-12-20」与系统链接，不含任何金额；再次发布被阻止并提示「2027 年度预算编制」，单位数不变；
任一单位缺填报人或审核人时整次发布失败并列出缺人单位，不生成单位、不发通知。
"""
import re
from collections import Counter

from sqlalchemy import func, select

from app.models import BudgetTask, Department, FillingUnit, NotificationOutbox, User
from tests.acceptance.e1_helpers import DEADLINE, FLOW09_ACTIVE_STORES, People, flow09_master, messages

AMOUNT = [re.compile(r"\d{1,3}(,\d{3})+"), re.compile(r"[¥$€£￥]"), re.compile(r"(?<![\d-])\d+\.\d+"),
          re.compile(r"\d{4,}(?!-)")]


def _publish(c):
    return c.post("/api/tasks", json={"year": 2027, "deadline": DEADLINE})


def test_flow_09_publish(seeded, dingtalk, stub, tmp_path):
    db = seeded
    flow09_master(db)
    p = People(db, dingtalk, tmp_path)
    lin = p("linxiao")
    r = _publish(lin)
    assert r.status_code == 201, r.text
    task_id = r.json()["task"]["id"]
    assert r.json()["task"]["name"] == "2027 年度预算编制"
    units = list(db.scalars(select(FillingUnit).where(FillingUnit.task_id == task_id)))
    assert len(units) == 24
    assert Counter(u.unit_type for u in units) == {"platform": 5, "b2b": 2, "cost_ratio": 1, "logistics_ratio": 1,
                                                   "dept_expense": 15}
    assert {u.name for u in units if u.unit_type == "platform"} == set(FLOW09_ACTIVE_STORES)
    assert "Lowes-US-02" not in {u.name for u in units}

    fillers = {u.filler_id for u in units}
    for fid in fillers:
        user = db.get(User, fid)
        mine = {m["id"] for m in p(user.dingtalk_userid).get("/api/filling-units", params={"mine": 1}).json()["items"]}
        assert {u.id for u in units if u.filler_id == fid} <= mine, user.name

    msgs = messages(db, dingtalk, stub)
    for fid in fillers:
        userid = db.get(User, fid).dingtalk_userid
        mine = [m for m in msgs if userid in m["userid_list"]]
        assert len(mine) == 1, (userid, mine)
        link = mine[0]["msg"]["link"]
        text = f"{link['title']} {link['text']}"
        assert "2027" in text and "2026-12-20" in text, text
        assert link["messageUrl"].startswith("http"), link
        stripped = text.replace("2026-12-20", "").replace("2027", "")
        assert not any(pt.search(stripped) for pt in AMOUNT), text
    assert len(msgs) == len(fillers)

    r = _publish(lin)
    assert r.status_code == 409 and "「2027 年度预算编制」" in r.json()["message"], r.text
    assert db.scalar(select(func.count()).select_from(FillingUnit)) == 24
    assert db.scalar(select(func.count()).select_from(BudgetTask)) == 1


def test_flow_09_missing_people(seeded, dingtalk, stub, tmp_path):
    db = seeded
    flow09_master(db)
    p = People(db, dingtalk, tmp_path)
    lin = p("linxiao")
    # 初始状态：研发部预算专员韩冰的角色已被林晓撤销（缺填报人，经角色与权限接口）；视觉部未设部门负责人（缺审核人，部门主数据）
    hb = db.scalar(select(User).where(User.name == "韩冰"))
    r = lin.put(f"/api/admin/users/{hb.id}/roles", json={"roles": []})
    assert r.status_code == 200, r.text
    db.scalar(select(Department).where(Department.name == "视觉部")).head_user_id = None
    db.flush()
    outbox = db.scalar(select(func.count()).select_from(NotificationOutbox))
    r = _publish(lin)
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "unit_missing_people"
    assert set(r.json()["details"]["units"]) == {"研发部", "视觉部"}, r.json()
    assert "研发部" in r.json()["message"] and "视觉部" in r.json()["message"]
    assert db.scalar(select(func.count()).select_from(FillingUnit)) == 0
    assert db.scalar(select(func.count()).select_from(BudgetTask)) == 0
    assert db.scalar(select(func.count()).select_from(NotificationOutbox)) == outbox
    assert messages(db, dingtalk, stub) == []
