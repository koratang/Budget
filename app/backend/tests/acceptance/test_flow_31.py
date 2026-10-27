"""FLOW-31 验收（真实路由 + 权限 + 数据库；审批经 API-F07-02）：预算规则库：预置规则、新建与可信度必选、审批生效转历史、退回与重新提交、额度标准 CEO 二级审批、
版本历史（AC-F12-01~07、NFR-004）。期望值逐字取自 TDD验收契约.md FLOW-31 行。"""
from sqlalchemy import select

from app.models import AuditLog
from tests.g3.conftest import g3  # noqa: F401

PRESETS = ["新渠道连续 2 个月收入达成率低于 70%", "部门费用额度使用率超出时间进度 10 个百分点以上",
           "品类毛利率比预算低 3 个百分点以上"]
MARGIN_ALERT = {"metric": "gross_margin_diff", "comparator": "lte", "threshold": "-2.5", "consecutive_months": 1,
                "applies_to": {"type": "category", "ids": []}, "receivers": ["finance_head", "operations"]}


def _ids(g3, items):
    return {i["name"]: i["id"] for i in items}


def approve(g3, rv_id, by="林晓"):
    r = g3.client(by).post(f"/api/approvals/rule-version/{rv_id}/approve")
    assert r.status_code == 200, r.text
    return r.json()


def reject(g3, rv_id, reason, by="林晓"):
    return g3.client(by).post(f"/api/approvals/rule-version/{rv_id}/reject", json={"reason": reason})


def test_flow_31_rule_library(g3):  # noqa: F811
    db = g3.db
    lin, chen = g3.client("林晓"), g3.client("陈思雨")
    # 首次启动：3 条预置待审批预警规则，可信度「未验证经验」
    items = lin.get("/api/rules").json()["items"]
    assert [i["name"] for i in items] == PRESETS
    for i in items:
        assert i["pending"]["status_label"] == "待审批" and i["pending"]["credibility_label"] == "未验证经验"
        assert i["effective_version_no"] is None
    # 预警规则表单字段：指标、比较方式、阈值、连续月数、适用对象、接收角色
    opts = lin.get("/api/rules/options").json()
    assert [m["label"] for m in opts["metrics"]] == ["收入达成率", "毛利率差", "额度使用率减时间进度", "额度使用率",
                                                     "预测偏差百分点"]
    assert opts["comparators"] and opts["applies"] and opts["receivers"]

    # 「品类毛利率比预算低 3 个百分点以上」：v1 审批生效后，陈思雨提交修改版
    margin_id = _ids(g3, items)[PRESETS[2]]
    detail = lin.get(f"/api/rules/{margin_id}").json()
    approve(g3, detail["versions"][0]["id"])
    cat = g3.category("浴室柜").id
    body = {"alert": {**MARGIN_ALERT, "applies_to": {"type": "category", "ids": [cat]}}, "basis": "2026 年 BI 回测"}
    r = chen.post(f"/api/rules/{margin_id}/versions", json=body)             # 不选可信度
    assert r.status_code == 422 and r.json()["message"] == "请选择可信度状态"
    r = chen.post(f"/api/rules/{margin_id}/versions", json={**body, "credibility": "observed"})
    assert r.status_code == 200, r.text
    v2 = r.json()["versions"][0]
    assert (v2["version_no"], v2["status_label"], v2["credibility_label"]) == (2, "待审批", "历史观察")
    assert v2["content"]["threshold"] == "-2.5" and v2["content"]["metric_label"] == "毛利率差"
    assert chen.post(f"/api/rules/{margin_id}/versions", json={**body, "credibility": "observed"}).status_code == 409
    approve(g3, v2["id"])
    vs = {v["version_no"]: v for v in lin.get(f"/api/rules/{margin_id}").json()["versions"]}
    assert (vs[2]["status_label"], vs[1]["status_label"]) == ("生效", "历史")

    # 新建规则：保存为待审批
    r = chen.post("/api/rules", json={"type": "driver_assumption", "name": "Amazon 美国站 11 月销量为 10 月的 1.6 倍",
                                     "content_text": "Amazon 美国站 11 月销量 = 10 月 × 1.4", "credibility": "unverified",
                                     "basis": "2025 年经验"})
    assert r.status_code == 200, r.text
    driver = r.json()
    assert driver["versions"][0]["status_label"] == "待审批"
    approve(g3, driver["versions"][0]["id"])
    r = chen.post(f"/api/rules/{driver['id']}/versions", json={"content_text": "Amazon 美国站 11 月销量 = 10 月 × 1.6",
                                                              "credibility": "observed", "basis": "2025–2026 金蝶"})
    approve(g3, r.json()["versions"][0]["id"])
    # v3（1.8 倍）林晓填原因退回 → 已退回不生效，v2 继续生效，提交人看到退回原因
    r = chen.post(f"/api/rules/{driver['id']}/versions", json={"content_text": "Amazon 美国站 11 月销量 = 10 月 × 1.8",
                                                              "credibility": "unverified", "basis": "运营经验判断"})
    v3_id = r.json()["versions"][0]["id"]
    r = reject(g3, v3_id, "  ")
    assert r.status_code == 422 and r.json()["message"] == "请填写退回原因"
    reason = "只有经验判断，没有历史数据支撑 1.8 倍"
    r = reject(g3, v3_id, reason)
    assert r.status_code == 200, r.text
    d = chen.get(f"/api/rules/{driver['id']}").json()
    vs = {v["version_no"]: v for v in d["versions"]}
    assert (vs[3]["status_label"], vs[2]["status_label"], vs[1]["status_label"]) == ("已退回", "生效", "历史")
    assert vs[3]["returned"]["reason"] == reason and vs[3]["returned"]["by"] == "林晓"
    assert d["resubmit"] is True and d["effective_version_no"] == 2
    r = chen.post(f"/api/rules/{driver['id']}/versions", json={"content_text": "Amazon 美国站 11 月销量 = 10 月 × 1.7",
                                                              "credibility": "observed", "basis": "补充 2024 年数据"})
    assert r.json()["versions"][0]["version_no"] == 4 and r.json()["versions"][0]["status_label"] == "待审批"

    # 额度标准：林晓通过后为待CEO审批，周明远通过后才生效
    r = chen.post("/api/rules", json={"type": "quota_standard", "name": "新渠道月收入放量上限",
                                     "content_text": "起始后第 1–12 个月逐月上限（人民币/店铺/月）",
                                     "limits": ["200000"] * 12, "credibility": "unverified", "basis": "财务负责人估计"})
    quota = r.json()
    qv = quota["versions"][0]["id"]
    approve(g3, qv)
    q = {v["id"]: v for v in chen.get(f"/api/rules/{quota['id']}").json()["versions"]}
    assert q[qv]["status_label"] == "待CEO审批"
    pend = g3.client("周明远").get("/api/approvals").json()["items"]
    assert [(i["type"], i["id"]) for i in pend if i["type"] == "rule-version"] == [("rule-version", qv)]
    approve(g3, qv, by="周明远")
    q = {v["id"]: v for v in chen.get(f"/api/rules/{quota['id']}").json()["versions"]}
    assert q[qv]["status_label"] == "生效"

    # 版本历史：内容、可信度、依据、提交人、审批人、生效时间
    v = lin.get(f"/api/rules/{driver['id']}").json()["versions"][-1]
    assert v["content"]["text"] and v["credibility_label"] == "未验证经验" and v["basis"] == "2025 年经验"
    assert v["submitted_by_name"] == "陈思雨" and v["approved_by_name"] == "林晓" and v["effective_at"]
    # CEO 只读，不能新建；其他角色无权访问
    assert g3.client("周明远").get("/api/rules").json()["can_create"] is False
    assert g3.client("周明远").post("/api/rules", json={}).status_code == 403
    assert g3.client("王浩").get("/api/rules").status_code == 403
    assert {"rule_created", "rule_version_submitted", "rule_version_approved", "rule_version_returned"} <= \
        set(db.scalars(select(AuditLog.action).where(AuditLog.object_type == "rule")))
