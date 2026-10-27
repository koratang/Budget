"""FLOW-29 验收（真实路由 + 权限 + 数据库）：导入后预警评估：只用生效版本、同一命中不重复、标记已处理（AC-F11-01~03、AC-F12-05）。

期望值逐字取自 TDD验收契约.md FLOW-29 行：物流物控部全年预算 1,200,000.00、1–4 月累计实际 560,000.00
→ 46.67% − 33.33% = 13.33 个百分点，阈值 10；人力资源部 8.33 个百分点不命中（待审批 v2 阈值 8 不参与）；
覆盖导入后累计 568,000.00 → 14.00 个百分点，记录总数仍为 1，未新增通知。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models import Alert, NotificationOutbox
from app.services import alerting
from tests.g3.conftest import g3  # noqa: F401
from tests.g3.fixtures_g3 import KINGDEE_HEADER, kd, write_xlsx

RULE = "部门费用额度使用率超出时间进度 10 个百分点以上"


def approve_http(g3, rv_id, by="林晓"):
    """经 API-F07-02 审批规则版本（真实路由 + 权限）。"""
    r = g3.client(by).post(f"/api/approvals/rule-version/{rv_id}/approve")
    assert r.status_code == 200, r.text
    return r.json()


def setup_budget_and_rule(g3):
    g3.set_now("2027-01-05 09:00")
    g3.make_version(depts={"物流物控部": 1200000, "人力资源部": 1200000})
    rule, v1 = g3.preset(RULE)
    approve_http(g3, v1.id)                       # 生效 v1（阈值 10）
    r = g3.client("陈思雨").post(f"/api/rules/{rule.id}/versions", json={
        "alert": {"metric": "usage_minus_time_progress", "comparator": "gte", "threshold": "8",
                  "consecutive_months": 1, "applies_to": {"type": "all"},
                  "receivers": ["dept_head", "finance_head", "ceo"]},
        "credibility": "observed", "basis": "2026 年金蝶回测"})
    assert r.status_code == 200, r.text                   # 待审批 v2（阈值 8）
    return rule, v1


def q1_history(g3, extra=()):
    rows = list(extra)
    for m in (1, 2, 3):
        p = f"2027-{m:02d}"
        rows += [kd(p, "工资", 120000, dept="物流物控部"), kd(p, "工资", 100000, dept="人力资源部")]
    return write_xlsx(g3.tmp / "金蝶_2027-01至03_费用.xlsx", KINGDEE_HEADER, rows)


def april(g3, logistics: int, name: str):
    rows = [kd("2027-04", "工资", logistics - 30000, dept="物流物控部"),
            kd("2027-04", "差旅", 30000, dept="物流物控部"),
            kd("2027-04", "工资", 200000, dept="人力资源部")]
    return write_xlsx(g3.tmp / name, KINGDEE_HEADER, rows)


def test_flow_29_alert_evaluation(g3):  # noqa: F811
    db = g3.db
    setup_budget_and_rule(g3)
    g3.set_now("2027-04-20 10:00")
    g3.import_file(q1_history(g3), "kingdee-history")
    assert db.scalar(select(func.count()).select_from(Alert)) == 0   # 1–3 月未超线

    g3.set_now("2027-05-12 10:00")
    g3.import_file(april(g3, 200000, "金蝶_2027-04_利润表.xlsx"), "kingdee")
    alerts = db.scalars(select(Alert)).all()
    assert len(alerts) == 1
    a = alerts[0]
    _rule, v1 = g3.preset(RULE)
    assert (a.object_type, a.object_name, a.period) == ("department", "物流物控部", date(2027, 4, 1))
    assert a.threshold == Decimal("0.1")
    assert round(a.metric_value * 100, 2) == Decimal("13.33")
    items = g3.client("林晓").get("/api/alerts").json()["items"]
    assert len(items) == 1
    item = items[0]
    assert (item["rule_name"], item["rule_version_no"], item["object_name"], item["period"]) == \
        (RULE, 1, "物流物控部", "2027-04")
    assert item["metric_display"] == "+13.33 个百分点"
    assert item["metric_parts"] == ["使用率 46.67%，时间进度 33.33%"]
    assert item["threshold_display"] == "≥ 10 个百分点"
    # 人力资源部 8.33 个百分点：即使待审批 v2 阈值 8 也不参与评估
    hr = alerting._usage_metrics(db, date(2027, 4, 1), "usage_minus_time_progress")[g3.dept("人力资源部").id][0]
    assert round(hr * 100, 2) == Decimal("8.33")
    assert [rv.version_no for _r, rv in alerting.effective_alert_rules(db)] == [1]
    notices = db.scalar(select(func.count()).select_from(NotificationOutbox).where(
        NotificationOutbox.biz_type == "alert"))
    assert notices == 1

    # 覆盖导入：同一记录指标值更新为 14.00 个百分点，记录总数仍为 1，未新增通知
    g3.set_now("2027-05-15 10:00")
    g3.import_file(april(g3, 208000, "金蝶_2027-04_利润表_更正.xlsx"), "kingdee", overwrite=True)
    db.expire_all()
    alerts = db.scalars(select(Alert)).all()
    assert len(alerts) == 1 and alerts[0].id == a.id
    assert round(alerts[0].metric_value * 100, 2) == Decimal("14.00")
    assert db.scalar(select(func.count()).select_from(NotificationOutbox).where(
        NotificationOutbox.biz_type == "alert")) == 1
    detail = g3.client("林晓").get(f"/api/alerts/{a.id}").json()
    assert detail["metric_display"] == "+14.00 个百分点"
    assert any("未新增记录、未重复通知" in c["text"] for c in detail["changes"])

    # 何建国标记已处理：未填说明提示「请填写处理说明」
    he = g3.client("何建国")
    r = he.post(f"/api/alerts/{a.id}/resolve", json={"note": "  "})
    assert r.status_code == 422 and r.json()["message"] == "请填写处理说明"
    assert g3.client("王浩").post(f"/api/alerts/{a.id}/resolve", json={"note": "x"}).status_code == 403
    note = "4 月集中支付全年海外仓年度服务费，属一次性预付，5–12 月不再发生该项支出"
    r = he.post(f"/api/alerts/{a.id}/resolve", json={"note": note})
    assert r.status_code == 200, r.text
    db.expire_all()
    a = db.get(Alert, a.id)
    assert a.status == "resolved" and a.resolved_by == g3.user("何建国").id and a.resolve_note == note
    assert a.resolved_at is not None
    assert r.json()["status_label"] == "已处理" and r.json()["resolved_by_name"] == "何建国"
