"""FLOW-18：三级审批、退回原因、提交 CEO 校验、CEO 退回与锁定（AC-F07-01~06）。

契约期望：提交后该单位出现在赵磊待处理列表，赵磊收到 1 条工作通知；无原因退回被阻止并提示「请填写退回原因」；
退回后状态「已退回」、可编辑、填报页显示退回原因原文，王浩收到工作通知；提交 CEO 被阻止并列出全部未通过单位名称；
CEO 退回后任务回到进行中并在任务详情显示 CEO 原因，林晓可对指定单位「退回给填报人」；
最终 CEO 通过后生成「年初原始目标」版本并锁定
"""
from sqlalchemy import select

from app.models import BudgetVersion, FillingUnit
from tests.g2.helpers import (grid, login, messages, minimal_units, publish, pu_key, save, submit, to_receiver,
                              unit_by_name)
from tests.g2.test_smoke_03 import _cells

REASON = "灯镜新品 10–12 月平均销量较 2026 同期高 40%"
CEO_REASON = "灯镜品类 2027 毛利率高于 2026 实际，请复核 Amazon-US-01 的采购成本占比与广告费率后重新提交。"


def _fill_submit_approve(client, db, unit, filler, head, cell):
    login(client, db, filler)
    assert save(client, unit.id, [cell]).json()["errors"] == []
    assert submit(client, unit.id).status_code == 200
    login(client, db, head)
    assert client.post(f"/api/approvals/unit/{unit.id}/approve").status_code == 200


def test_flow_18_three_level_approval(seeded, client, dingtalk, stub):
    db = seeded
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    amz = unit_by_name(db, task_id, "Amazon-US-01")
    key = pu_key(db, "Amazon-US-01", "灯镜", True, "avg_sales")
    stub.delete("/_stub/messages")
    messages(db, dingtalk, stub)  # 发布通知先发出
    stub.delete("/_stub/messages")

    login(client, db, "wanghao")
    assert save(client, amz.id, [(key, "2027-10", "120")]).json()["errors"] == []
    assert submit(client, amz.id).status_code == 200
    login(client, db, "zhaolei")
    items = client.get("/api/approvals").json()["items"]
    assert [(i["type"], i["id"]) for i in items] == [("unit", amz.id)]
    assert len(to_receiver(messages(db, dingtalk, stub), "zhaolei")) == 1

    r = client.post(f"/api/approvals/unit/{amz.id}/reject", json={"reason": "  "})
    assert r.status_code == 422 and r.json()["message"] == "请填写退回原因"
    r = client.post(f"/api/approvals/unit/{amz.id}/reject", json={"reason": REASON})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    login(client, db, "wanghao")
    info = grid(client, amz.id)["unit"]
    assert info["status_label"] == "已退回" and info["editable"] is True
    assert info["return_reason"] == REASON and info["returned_by"] == "赵磊"
    wang = to_receiver(messages(db, dingtalk, stub), "wanghao")
    assert len(wang) == 1 and "退回" in wang[0]["msg"]["link"]["title"]

    assert save(client, amz.id, [(key, "2027-10", "100")]).json()["errors"] == []
    assert submit(client, amz.id).status_code == 200
    login(client, db, "zhaolei")
    assert client.post(f"/api/approvals/unit/{amz.id}/approve").json()["status"] == "approved"

    # 仍有单位未通过时提交 CEO 被阻止并列出全部未通过单位名称
    login(client, db, "linxiao")
    r = client.post(f"/api/tasks/{task_id}/submit-to-ceo")
    assert r.status_code == 422
    assert {u["name"] for u in r.json()["details"]["units"]} == {"B端 · 美国业务部", "成本比例（财务BP）",
                                                                  "物流比例（物流物控）", "人力资源部"}

    cells = _cells(db)
    for name, (filler, head, cell) in cells.items():
        if name != "Amazon-US-01":
            _fill_submit_approve(client, db, unit_by_name(db, task_id, name), filler, head, cell)
    login(client, db, "linxiao")
    assert client.post(f"/api/tasks/{task_id}/submit-to-ceo").json()["status"] == "pending_ceo"

    login(client, db, "zhoumingyuan")
    assert [(i["type"], i["id"]) for i in client.get("/api/approvals").json()["items"]] == [("task", task_id)]
    assert client.post(f"/api/approvals/task/{task_id}/reject", json={"reason": ""}).status_code == 422
    r = client.post(f"/api/approvals/task/{task_id}/reject", json={"reason": CEO_REASON})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"

    login(client, db, "linxiao")
    p = client.get(f"/api/tasks/{task_id}/progress").json()
    assert p["task"]["status"] == "in_progress" and p["task"]["status_label"] == "CEO 已退回"
    assert p["ceo_return"]["reason"] == CEO_REASON and p["ceo_return"]["by"] == "周明远"
    r = client.post(f"/api/tasks/{task_id}/units/{amz.id}/return", json={"reason": ""})
    assert r.status_code == 422 and r.json()["message"] == "请填写退回原因"
    r = client.post(f"/api/tasks/{task_id}/units/{amz.id}/return", json={"reason": "请按 CEO 意见复核广告费率"})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    p = client.get(f"/api/tasks/{task_id}/progress").json()
    amz_row = next(u for u in p["units"] if u["id"] == amz.id)
    assert amz_row["return_reason_display"] == "林晓：请按 CEO 意见复核广告费率"

    _fill_submit_approve(client, db, amz, "wanghao", "zhaolei", (key, "2027-10", "95"))
    login(client, db, "linxiao")
    assert client.post(f"/api/tasks/{task_id}/submit-to-ceo").json()["status"] == "pending_ceo"
    login(client, db, "zhoumingyuan")
    d = client.get(f"/api/approvals/task/{task_id}").json()
    assert d["can_act"] is True and d["approve_label"] == "通过并锁定"
    r = client.post(f"/api/approvals/task/{task_id}/approve")
    assert r.status_code == 200 and r.json()["status"] == "completed"
    v = db.scalar(select(BudgetVersion).where(BudgetVersion.id == db.get(FillingUnit, amz.id).version_id))
    db.refresh(v)
    assert v.type == "original_target" and v.locked is True and v.approved_by is not None
