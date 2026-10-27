"""SMOKE-03：发布任务 → 各填报人填一个单元并提交 → 部门负责人通过 → 提交 CEO → CEO 通过并锁定（API 层；浏览器 E2E 另行执行）。

契约期望：每个单位状态依次显示未开始→填报中→已提交→已通过；任务状态依次为进行中→待CEO审批→已完成；
版本列表出现「年初原始目标」且带锁定标记；随后任一身份修改该版本任一单元均被拒绝且数值不变。
"""
from sqlalchemy import select, update

from app.models import BudgetVersion, FillingUnit, Store
from tests.g2.helpers import (account, customer, grid, login, minimal_units, publish, pu_key, row, save, store,
                              submit)

# 各单位：(单位名称, 填报人, 部门负责人, 一个单元)
def _cells(db):
    hr = account(db, "工资薪酬").id
    fer = customer(db, "Ferguson").id
    amz = store(db, "Amazon-US-01")
    return {
        "Amazon-US-01": ("wanghao", "zhaolei", (pu_key(db, "Amazon-US-01", "浴室柜", True, "spu_count"), "2027-03", "10")),
        "B端 · 美国业务部": ("sunting", "hanliqun", (f"b2b:{fer}|sales_local", "2027-03", "200000")),
        "成本比例（财务BP）": ("chensiyu", "linxiao",
                         (f"ccr:{amz.channel_id}:{amz.site_id}:{_cat(db)}|purchase_cost_rate", "2027-03", "30")),
        "物流比例（物流物控）": ("jiangfan", "hejianguo",
                         (f"ccr:{amz.channel_id}:{amz.site_id}:{_cat(db)}|first_leg_rate", "2027-03", "6")),
        "人力资源部": ("zhengke", "wujing", (f"de:{hr}|amount", "2027-03", "300000")),
    }


def _cat(db):
    from tests.g2.helpers import category_id
    return category_id(db, "浴室柜")


def test_smoke_03_publish_fill_approve_lock(seeded, client):
    db = seeded
    # 最小种子：1 个启用店铺 Amazon-US-01
    db.execute(update(Store).where(Store.name != "Amazon-US-01").values(is_active=False))
    r = publish(client, db, minimal_units(db))
    assert r.status_code == 201, r.text
    task_id = r.json()["task"]["id"]
    assert r.json()["task"]["status_label"] == "进行中"
    cells = _cells(db)
    units = {u.name: u for u in db.scalars(select(FillingUnit).where(FillingUnit.task_id == task_id))}
    assert set(units) == set(cells)
    seen: dict[str, list[str]] = {name: [u.status] for name, u in units.items()}

    for name, (filler, head, (key, field, value)) in cells.items():
        uid_ = units[name].id
        login(client, db, filler)
        r = save(client, uid_, [(key, field, value)])
        assert r.status_code == 200 and r.json()["errors"] == [], r.text
        seen[name].append(r.json()["grid"]["unit"]["status"])
        r = submit(client, uid_)
        assert r.status_code == 200, r.text
        seen[name].append(r.json()["status"])
        login(client, db, head)
        r = client.post(f"/api/approvals/unit/{uid_}/approve")
        assert r.status_code == 200, r.text
        seen[name].append(r.json()["status"])
    for name, states in seen.items():
        assert states == ["not_started", "filling", "submitted", "approved"], name  # 未开始→填报中→已提交→已通过

    login(client, db, "linxiao")
    r = client.post(f"/api/tasks/{task_id}/submit-to-ceo")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_ceo"  # 待CEO审批
    login(client, db, "zhoumingyuan")
    r = client.post(f"/api/approvals/task/{task_id}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"  # 已完成
    version = db.get(BudgetVersion, r.json()["version"]["id"])
    db.refresh(version)
    assert version.type == "original_target" and version.locked  # 「年初原始目标」带锁定标记
    assert r.json()["version"]["name"] == "2027 年初原始目标"

    # 随后任一身份修改该版本任一单元均被拒绝且数值不变
    for name, (filler, _, (key, field, _value)) in cells.items():
        uid_ = units[name].id
        for who in (filler, "linxiao", "chensiyu", "zhoumingyuan"):
            login(client, db, who)
            r = client.get(f"/api/filling-units/{uid_}/grid")
            before = row(r.json(), key)["values"][field]
            r = save(client, uid_, [(key, field, "1")])
            assert r.status_code in (403, 409), (name, who, r.text)
            if r.status_code == 409:
                assert r.json()["message"] == "版本已锁定，不能修改"
            assert row(grid(client, uid_), key)["values"][field] == before
