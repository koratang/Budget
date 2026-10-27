"""FLOW-20 季度滚动预测与快照（API 层验收，真实路由 + 数据库 + 钉钉本地替身）。期望值逐字取自 TDD验收契约.md FLOW-20：

Q1 快照逐月数值与 V1 相同且无需任何填报人提交；发起 Q2 时上述四类角色各收到工作通知，填报表只开放 4–12 月、1–3 月不可编辑；
Q2 快照中 2027-04 Amazon-US-01 收入取 ¥ 554,400.00（实际），5–12 月取最新提交的驱动计算值；
快照标注发布日期与「2027 Q2」，修改被拒

前置：V1 经完整编制审批生成（Amazon-US-01 每月驱动计算值 ¥ 600,000.00）；金蝶实际经导入接口导入。
填报人更新走「我的填报」滚动预测入口对应的同一表格接口 /api/filling-units/rolling/{版本}/{单位键}/cells，不在服务层模拟。
"""
from decimal import Decimal

from sqlalchemy import select

from app.models import AuditLog, User, UserRole
from app.models.enums import Role
from tests.acceptance.e2_common import Ctx, actual_rows_2027
from tests.g2.helpers import messages, pu_key, store

NEW_SALES = "78"
# 最新提交的驱动计算值（按需求公式手算）：15 × 78 × 77.65 USD × (1 − 0%) × 7.12
FORECAST = Decimal(15) * Decimal(78) * Decimal("77.65") * Decimal("7.12")


def test_flow_20_rolling_forecast(seeded, client, dingtalk, stub):
    db = seeded
    ctx = Ctx(db, client)
    v1 = ctx.build_v1()
    ctx.now("2027-01-05 10:00")
    messages(db, dingtalk, stub)
    stub.delete("/_stub/messages")

    # 2027-01-08 林晓「以年初原始目标发布」Q1 快照
    ctx.now("2027-01-08 10:00")
    ctx.login("linxiao")
    assert client.get("/api/versions").json()["actions"]["publish_original"]["visible"] is True
    r = client.post("/api/versions/rolling/publish-original")
    assert r.status_code == 200, r.text
    q1 = r.json()["id"]
    s_q1 = client.get(f"/api/versions/{q1}/summary").json()["months"]
    s_v1 = client.get(f"/api/versions/{v1}/summary").json()["months"]
    pick = lambda ms: [(m["month"], m["revenue"], m["gross"], m["net"]) for m in ms]  # noqa: E731
    assert pick(s_q1) == pick(s_v1) and len(s_q1) == 12
    assert not db.scalar(select(AuditLog).where(AuditLog.action == "rolling_unit_submitted"))  # 无需任何填报人提交

    # 2027-04-10 已导入 1–3 月实际；2027-04-22 发起 Q2 滚动预测更新
    ctx.now("2027-04-10 10:00")
    ctx.import_kingdee(actual_rows_2027([1, 2, 3]), "金蝶_2027-01至03_利润表.xlsx")
    messages(db, dingtalk, stub)
    stub.delete("/_stub/messages")
    ctx.now("2027-04-22 09:00")
    ctx.login("linxiao")
    r = client.post("/api/versions/rolling")
    assert r.status_code == 200, r.text
    draft = r.json()["id"]
    msgs = messages(db, dingtalk, stub)
    received = {u for m in msgs for u in m["userid_list"]}
    for role in (Role.OPERATIONS, Role.B2B, Role.LOGISTICS, Role.FINANCE_BP):
        ids = set(db.scalars(select(User.dingtalk_userid).join(UserRole, UserRole.user_id == User.id)
                             .where(UserRole.role_code == role)))
        assert ids and ids <= received, (role, ids - received)

    # 王浩从「我的填报」滚动预测入口进入表格：只开放 4–12 月
    ctx.login("wanghao")
    mine = client.get("/api/filling-units?mine=1").json()["items"]
    item = next(u for u in mine if u["rolling"] and u["name"] == "Amazon-US-01")
    base = f"/api/filling-units/rolling/{item['rolling']['version_id']}/{item['rolling']['key']}"
    assert item["rolling"]["version_id"] == draft
    key = pu_key(db, "Amazon-US-01", "浴室柜", False, "avg_sales")
    g = ctx.grid(f"{base}/grid")
    row = next(x for x in g["rows"] if x["key"] == key)
    assert {f"2027-{m:02d}" for m in (1, 2, 3)} <= set(row["readonly_fields"])
    assert not {f"2027-{m:02d}" for m in range(4, 13)} & set(row["readonly_fields"])
    r = ctx.save(base, [(key, "2027-02", NEW_SALES)])
    assert r.status_code == 200 and [e["code"] for e in r.json()["errors"]] == ["month_locked"]
    ctx.save_ok(base, [(key, f"2027-{m:02d}", NEW_SALES) for m in range(5, 13)])
    r = client.post(f"{base}/submit")
    assert r.status_code == 200, r.text

    # 运营、B端业务、物流物控、财务BP 其余单位更新并提交
    ctx.login("linxiao")
    units = client.get(f"/api/versions/rolling/{draft}").json()["units"]
    for u in units:
        if u["submitted"]:
            continue
        ctx.login(db.get(User, u["filler_id"]).dingtalk_userid)
        r = client.post(f"/api/filling-units/rolling/{draft}/{u['key']}/submit")
        assert r.status_code == 200, (u["name"], r.text)

    # 金蝶 2027-04 实际已导入（Amazon-US-01 实际收入 ¥ 554,400.00）
    ctx.now("2027-05-10 16:00")
    ctx.import_kingdee(actual_rows_2027([4], amz_april="554400"), "金蝶_2027-04_利润表.xlsx")

    # 2027-05-12 林晓发布 Q2 快照
    ctx.now("2027-05-12 10:00")
    ctx.login("linxiao")
    r = client.post(f"/api/versions/rolling/{draft}/publish", json={"confirm_unsubmitted": True})
    assert r.status_code == 200, r.text
    assert (r.json()["quarter_label"], r.json()["published_on"]) == ("2027 Q2", "2027-05-12")
    amz = store(db, "Amazon-US-01")
    by = {m["month"]: m for m in client.get(f"/api/versions/{draft}/summary",
                                            params={"store_id": amz.id}).json()["months"]}
    assert by["2027-04"]["revenue_display"] == "¥ 554,400.00" and by["2027-04"]["source"] == "actual"
    for m in range(5, 13):
        assert Decimal(by[f"2027-{m:02d}"]["revenue"]) == FORECAST, m
        assert by[f"2027-{m:02d}"]["source"] == "forecast"
    # 2027-04 驱动计算值仍为 ¥ 600,000.00（快照不取）
    v1_by = {m["month"]: m for m in client.get(f"/api/versions/{v1}/summary",
                                               params={"store_id": amz.id}).json()["months"]}
    assert v1_by["2027-04"]["revenue_display"] == "¥ 600,000.00"
    row = next(v for v in client.get("/api/versions").json()["versions"] if v["id"] == draft)
    assert (row["quarter_label"], row["published_on"], row["status_label"]) == ("2027 Q2", "2027-05-12", "不可修改")

    # 尝试修改快照被拒：再次发布 / 经表格接口写入
    assert client.post(f"/api/versions/rolling/{draft}/publish", json={"confirm_unsubmitted": True}).status_code == 409
    ctx.login("wanghao")
    before = by["2027-06"]["revenue"]
    r = client.patch(f"{base}/cells", json=[{"row_key": key, "field": "2027-06", "value": "99", "base": NEW_SALES}])
    assert r.status_code in (403, 409, 422), r.text
    ctx.login("linxiao")
    after = {m["month"]: m for m in client.get(f"/api/versions/{draft}/summary",
                                               params={"store_id": amz.id}).json()["months"]}
    assert after["2027-06"]["revenue"] == before
