"""SMOKE-03 验收（API 层，真实路由 + 数据库）：期望值逐字取自 TDD验收契约 SMOKE-03。

最小种子 → 林晓发布「2027 年度预算编制」→ 各填报人填一个单元并提交 → 各部门负责人通过 → 林晓「提交 CEO 审批」
→ 周明远「通过并锁定」。每个单位状态依次显示未开始→填报中→已提交→已通过；任务状态依次为进行中→待CEO审批→已完成；
版本列表出现「年初原始目标」且带锁定标记；随后任一身份修改该版本任一单元均被拒绝且数值不变。
"""
from sqlalchemy import select

from app.models import BudgetAccount, BCustomer, Category, FillingUnit, Store
from tests.acceptance.e1_helpers import DEADLINE, People, grid, row, save, smoke03_master


def _cell_plan(db):
    amz = db.scalar(select(Store).where(Store.name == "Amazon-US-01"))
    cat = db.scalar(select(Category.id).where(Category.name == "浴室柜"))
    fer = db.scalar(select(BCustomer.id).where(BCustomer.name == "Ferguson"))
    salary = db.scalar(select(BudgetAccount.id).where(BudgetAccount.name == "工资薪酬"))
    ccr = f"ccr:{amz.channel_id}:{amz.site_id}:{cat}"
    return {  # 单位 → (填报人, 部门负责人, (row_key, 月份, 值))
        "Amazon-US-01": ("wanghao", "zhaolei", (f"pu:{amz.id}:{amz.site_id}:{cat}:1|spu_count", "2027-03", "10")),
        "B端 · 美国业务部": ("sunting", "hanliqun", (f"b2b:{fer}|sales_local", "2027-03", "200000")),
        "成本比例（财务BP）": ("chensiyu", "linxiao", (f"{ccr}|purchase_cost_rate", "2027-03", "30")),
        "物流比例（物流物控）": ("jiangfan", "hejianguo", (f"{ccr}|first_leg_rate", "2027-03", "6")),
        "人力资源部": ("zhengke", "wujing", (f"de:{salary}|amount", "2027-03", "300000")),
    }


def _progress_labels(c, task_id):
    p = c.get(f"/api/tasks/{task_id}/progress").json()
    return {u["name"]: u["status_label"] for u in p["units"]}, p["task"]


def test_smoke_03(seeded, dingtalk):
    db = seeded
    smoke03_master(db)
    p = People(db, dingtalk)
    lin = p("linxiao")
    cands = lin.get("/api/tasks/candidates").json()["items"]
    r = lin.post("/api/tasks", json={"year": 2027, "deadline": DEADLINE,
                                     "units": [{"unit_type": c["unit_type"], "scope_object_id": c["scope_object_id"]}
                                               for c in cands]})
    assert r.status_code == 201, r.text
    task_id = r.json()["task"]["id"]
    assert r.json()["task"]["name"] == "2027 年度预算编制"
    plan = _cell_plan(db)
    labels, task = _progress_labels(lin, task_id)
    assert set(labels) == set(plan)
    task_states = [task["status_label"]]
    seen = {name: [st] for name, st in labels.items()}

    units = {u.name: u.id for u in db.scalars(select(FillingUnit).where(FillingUnit.task_id == task_id))}
    for name, (filler, head, (key, field, value)) in plan.items():
        r = save(p(filler), units[name], [(key, field, value)])
        assert r.status_code == 200 and r.json()["errors"] == [], r.text
        seen[name].append(_progress_labels(lin, task_id)[0][name])
        r = p(filler).post(f"/api/filling-units/{units[name]}/submit")
        assert r.status_code == 200, r.text
        seen[name].append(_progress_labels(lin, task_id)[0][name])
        r = p(head).post(f"/api/approvals/unit/{units[name]}/approve")
        assert r.status_code == 200, r.text
        seen[name].append(_progress_labels(lin, task_id)[0][name])
    for name, states in seen.items():
        assert states == ["未开始", "填报中", "已提交", "已通过"], (name, states)

    r = lin.post(f"/api/tasks/{task_id}/submit-to-ceo")
    assert r.status_code == 200, r.text
    task_states.append(_progress_labels(lin, task_id)[1]["status_label"])
    r = p("zhoumingyuan").post(f"/api/approvals/task/{task_id}/approve")
    assert r.status_code == 200, r.text
    task_states.append(_progress_labels(lin, task_id)[1]["status_label"])
    # 任务状态依次为 进行中 → 待CEO审批 → 已完成（任务详情 / 编制任务列表显示文字）
    assert task_states == ["进行中", "待CEO审批", "已完成"], task_states
    listed = next(t for t in lin.get("/api/tasks").json()["items"] if t["id"] == task_id)
    assert listed["status_label"] == "已完成"

    vers = p("zhoumingyuan").get("/api/versions", params={"year": 2027})
    assert vers.status_code == 200, vers.text
    items = vers.json()["versions"]
    original = [v for v in items if v["type_label"] == "年初原始目标"]
    assert len(original) == 1 and original[0]["status_label"].startswith("已锁定"), items

    # 随后任一身份修改该版本任一单元均被拒绝且数值不变
    everyone = ["linxiao", "zhoumingyuan", "chensiyu", "wanghao", "sunting", "jiangfan", "zhengke", "wujing",
                "zhaolei", "hanliqun", "hejianguo"]
    for name, (_f, _h, (key, field, value)) in plan.items():
        before = row(grid(p(plan[name][0]), units[name]), key)["values"][field]
        for who in everyone:
            c = p(who)
            r = save(c, units[name], [(key, field, "1")]) if c.get(
                f"/api/filling-units/{units[name]}/grid").status_code == 200 else c.patch(
                f"/api/filling-units/{units[name]}/cells", json=[{"row_key": key, "field": field, "value": "1",
                                                                  "base": value}])
            assert r.status_code in (403, 409), (name, who, r.status_code, r.text)
        assert row(grid(p(plan[name][0]), units[name]), key)["values"][field] == before, name
