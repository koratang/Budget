"""FLOW-09：发布编制任务 → 按 AC-F03-05 生成 24 个填报单位 → 通知每位填报人；同年度再次发布被阻止；缺人整次失败。

契约期望：生成 24 个填报单位：平台渠道 5（停用店铺无单位）、B 端 2、成本比例 1、物流比例 1、部门费用 15，
各单位独立出现在对应填报人的「我的填报」；每个单位填报人收到 1 条工作通知，内容含「2027」「2026-12-20」与系统链接，
不含任何金额；第二次发布被阻止并提示已有任务名称「2027 年度预算编制」，单位数不变；
任一单位缺填报人或审核人时整次发布失败并列出缺人单位，不生成单位、不发通知。
"""
import re
from collections import Counter

from sqlalchemy import delete, func, select, update

from app.models import BudgetTask, Department, FillingUnit, NotificationOutbox, Store, User, UserRole, UserScope
from tests.g2.helpers import add_user, login, messages, publish

ACTIVE_STORES = ("Amazon-US-01", "Amazon-CA-01", "Wayfair-US-01", "Shopify-US-01", "TikTok-US-01")
DISABLED_STORE = "Lowes-US-02"
# 补齐 15 个参与部门的部门预算专员与部门负责人（种子只有人力资源部的专员）
EXTRA_PEOPLE = {
    "产品作战部": ("许嘉", "沈卓"), "开发部": ("宋宇", "顾磊"), "研发部": ("韩冰", "钱峰"), "供应中心": ("冯涛", "陆军"),
    "运营部": ("曹敏", None), "市场部": ("邓琳", "孔亮"), "美国业务部": ("周凯", None), "视觉部": ("彭悦", "范婷"),
    "外贸部": ("江涛", None), "物流物控部": ("吕彬", None), "项目管理部": ("唐瑶", "黎明"),
    "信息数字化部": ("董杰", "邵阳"), "财务部": ("郭琪", None), "总经办": ("袁芳", None),
}
AMOUNT = [re.compile(r"\d{1,3}(,\d{3})+"), re.compile(r"[¥$€£￥]"), re.compile(r"(?<![\d-])\d+\.\d+")]


def setup_flow09(db) -> None:
    """种子主数据 5 个启用店铺 + 停用店铺、美国业务部与外贸部各有启用客户、15 个参与部门。"""
    db.execute(update(Store).where(Store.name.not_in(ACTIVE_STORES)).values(is_active=False))
    for i, (dept, (budget_name, head_name)) in enumerate(EXTRA_PEOPLE.items()):
        d = db.scalar(select(Department).where(Department.name == dept))
        add_user(db, f"g2-budget-{i}", budget_name, dept, ["dept_budget"], {"department": [d.id]})
        if head_name:
            add_user(db, f"g2-head-{i}", head_name, dept, ["dept_head"], {"department": [d.id]}, head=True)


def test_flow_09_publish_units_and_notices(seeded, client, dingtalk, stub):
    db = seeded
    setup_flow09(db)
    r = publish(client, db)
    assert r.status_code == 201, r.text
    task_id = r.json()["task"]["id"]
    units = list(db.scalars(select(FillingUnit).where(FillingUnit.task_id == task_id)))
    assert len(units) == 24
    assert Counter(u.unit_type for u in units) == {"platform": 5, "b2b": 2, "cost_ratio": 1, "logistics_ratio": 1,
                                                   "dept_expense": 15}
    assert {u.name for u in units if u.unit_type == "platform"} == set(ACTIVE_STORES)
    assert DISABLED_STORE not in {u.name for u in units}

    # 各单位独立出现在对应填报人的「我的填报」
    fillers = {u.filler_id for u in units}
    for filler_id in fillers:
        user = db.get(User, filler_id)
        login(client, db, user.dingtalk_userid)
        mine = client.get("/api/filling-units", params={"mine": 1}).json()["items"]
        expected = {u.id for u in units if u.filler_id == filler_id}
        assert expected <= {m["id"] for m in mine}, user.name
    login(client, db, "wanghao")
    assert [m["name"] for m in client.get("/api/filling-units?mine=1").json()["items"]] == ["Amazon-US-01"]

    # 每个单位填报人收到 1 条工作通知：含「2027」「2026-12-20」与系统链接，不含金额
    msgs = messages(db, dingtalk, stub)
    for filler_id in fillers:
        userid = db.get(User, filler_id).dingtalk_userid
        mine = [m for m in msgs if userid in m["userid_list"]]
        assert len(mine) == 1, userid
        link = mine[0]["msg"]["link"]
        text = f"{link['title']} {link['text']}"
        assert "2027" in text and "2026-12-20" in text
        assert link["messageUrl"].startswith("http") and link["messageUrl"].endswith("/filling")
        assert not any(p.search(text.replace("2026-12-20", "")) for p in AMOUNT), text

    # 第二次发布被阻止并提示已有任务名称「2027 年度预算编制」，单位数不变
    r = publish(client, db)
    assert r.status_code == 409
    assert "「2027 年度预算编制」" in r.json()["message"]
    assert db.scalar(select(func.count()).select_from(FillingUnit)) == 24
    assert db.scalar(select(func.count()).select_from(BudgetTask)) == 1


def test_flow_09_missing_people_blocks_whole_publish(seeded, client):
    db = seeded
    setup_flow09(db)
    # 研发部没有部门预算专员 → 该单位缺填报人；视觉部负责人缺失 → 缺审核人
    rd = db.scalar(select(Department).where(Department.name == "研发部"))
    budget_users = select(UserScope.user_id).where(UserScope.scope_type == "department", UserScope.object_id == rd.id)
    db.execute(delete(UserRole).where(UserRole.role_code == "dept_budget", UserRole.user_id.in_(budget_users)))
    db.execute(update(Department).where(Department.name == "视觉部").values(head_user_id=None))
    outbox_before = db.scalar(select(func.count()).select_from(NotificationOutbox))
    r = publish(client, db)
    assert r.status_code == 422
    assert r.json()["code"] == "unit_missing_people"
    assert set(r.json()["details"]["units"]) == {"研发部", "视觉部"}
    assert "研发部" in r.json()["message"] and "视觉部" in r.json()["message"]
    assert db.scalar(select(func.count()).select_from(FillingUnit)) == 0
    assert db.scalar(select(func.count()).select_from(BudgetTask)) == 0
    assert db.scalar(select(func.count()).select_from(NotificationOutbox)) == outbox_before
