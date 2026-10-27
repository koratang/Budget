"""FLOW-18 三级审批（API 层验收，钉钉本地替身）。期望值逐字取自 TDD验收契约.md FLOW-18：
提交后该单位出现在赵磊待处理列表，赵磊收到 1 条工作通知；无原因退回被阻止并提示「请填写退回原因」；退回后状态「已退回」、
可编辑、填报页显示退回原因原文，王浩收到工作通知；提交 CEO 被阻止并列出全部未通过单位名称；CEO 退回后任务回到进行中并在
任务详情显示 CEO 原因，林晓可对指定单位「退回给填报人」；最终 CEO 通过后生成「年初原始目标」版本并锁定
"""
from sqlalchemy import select

from app.models import BudgetVersion, FillingUnit
from tests.acceptance.e2_common import Ctx
from tests.g2.helpers import messages, pu_key, to_receiver
from tests.g2.test_smoke_03 import _cells

REASON = "灯镜新品 10–12 月平均销量较 2026 同期高 40%"
CEO_REASON = "请复核 Amazon-US-01 的广告费率后重新提交"


def test_flow_18(seeded, client, dingtalk, stub):
    db = seeded
    ctx = Ctx(db, client)
    task = ctx.publish()
    amz = ctx.unit(task, "Amazon-US-01")
    key = pu_key(db, "Amazon-US-01", "灯镜", True, "avg_sales")
    messages(db, dingtalk, stub)
    stub.delete("/_stub/messages")

    ctx.login("wanghao")
    ctx.save_ok(f"/api/filling-units/{amz}", [(key, "2027-10", "120")])
    assert client.post(f"/api/filling-units/{amz}/submit").status_code == 200
    ctx.login("zhaolei")
    assert ("unit", amz) in [(i["type"], i["id"]) for i in client.get("/api/approvals").json()["items"]]
    assert len(to_receiver(messages(db, dingtalk, stub), "zhaolei")) == 1
    r = client.post(f"/api/approvals/unit/{amz}/reject", json={"reason": ""})
    assert r.status_code == 422 and r.json()["message"] == "请填写退回原因"
    r = client.post(f"/api/approvals/unit/{amz}/reject", json={"reason": REASON})
    assert r.status_code == 200
    ctx.login("wanghao")
    info = ctx.grid(f"/api/filling-units/{amz}/grid")["unit"]
    assert (info["status_label"], info["editable"], info["return_reason"]) == ("已退回", True, REASON)
    assert len(to_receiver(messages(db, dingtalk, stub), "wanghao")) == 1
    ctx.save_ok(f"/api/filling-units/{amz}", [(key, "2027-10", "100")])
    assert client.post(f"/api/filling-units/{amz}/submit").status_code == 200
    ctx.login("zhaolei")
    assert client.post(f"/api/approvals/unit/{amz}/approve").status_code == 200

    ctx.login("linxiao")
    r = client.post(f"/api/tasks/{task}/submit-to-ceo")
    assert r.status_code == 422
    assert {u["name"] for u in r.json()["details"]["units"]} == {"B端 · 美国业务部", "成本比例（财务BP）",
                                                                  "物流比例（物流物控）", "人力资源部"}
    for name, (filler, head, cell) in _cells(db).items():
        if name == "Amazon-US-01":
            continue
        uid_ = ctx.unit(task, name)
        tab = "platform" if "比例" in name else None
        ctx.login(filler)
        ctx.save_ok(f"/api/filling-units/{uid_}", [cell], tab=tab)
        assert client.post(f"/api/filling-units/{uid_}/submit").status_code == 200
        ctx.login(head)
        assert client.post(f"/api/approvals/unit/{uid_}/approve").status_code == 200
    ctx.login("linxiao")
    assert client.post(f"/api/tasks/{task}/submit-to-ceo").json()["status"] == "pending_ceo"
    ctx.login("zhoumingyuan")
    assert client.post(f"/api/approvals/task/{task}/reject", json={"reason": " "}).status_code == 422
    r = client.post(f"/api/approvals/task/{task}/reject", json={"reason": CEO_REASON})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    ctx.login("linxiao")
    p = client.get(f"/api/tasks/{task}/progress").json()
    assert p["task"]["status"] == "in_progress" and p["ceo_return"]["reason"] == CEO_REASON
    r = client.post(f"/api/tasks/{task}/units/{amz}/return", json={"reason": "请按 CEO 意见复核广告费率"})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    ctx.login("wanghao")
    ctx.save_ok(f"/api/filling-units/{amz}", [(key, "2027-10", "95")])
    assert client.post(f"/api/filling-units/{amz}/submit").status_code == 200
    ctx.login("zhaolei")
    assert client.post(f"/api/approvals/unit/{amz}/approve").status_code == 200
    ctx.login("linxiao")
    assert client.post(f"/api/tasks/{task}/submit-to-ceo").json()["status"] == "pending_ceo"
    ctx.login("zhoumingyuan")
    assert client.get(f"/api/approvals/task/{task}").json()["approve_label"] == "通过并锁定"
    assert client.post(f"/api/approvals/task/{task}/approve").json()["status"] == "completed"
    v = db.get(BudgetVersion, db.scalar(select(FillingUnit.version_id).where(FillingUnit.id == amz)))
    db.refresh(v)
    assert v.type == "original_target" and v.locked is True
    ctx.login("linxiao")
    row = next(x for x in client.get("/api/versions").json()["versions"] if x["id"] == v.id)
    assert row["type_label"] == "年初原始目标"
