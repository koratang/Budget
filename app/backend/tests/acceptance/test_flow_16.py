"""FLOW-16 部门费用填报、历史参考与专项预留额度（API 层验收）。期望值逐字取自 TDD验收契约.md FLOW-16：
填报按「预算科目 × 月」提供人民币金额；培训费 2027-04 单元下显示上年同月实际 35,000.00，行尾「近 12 月实际合计」420,000.00，
员工关怀费行显示「无历史数据」；新增专项后培训费 2027-04 预算变为 230,000.00 且专项列表出现该专项，
专项行「上年同科目实际（2026-01～11，12 月未导入）」显示 390,000.00；登记后已用 96,000.00、剩余 84,000.00
"""
from tests.acceptance.e2_common import Ctx, kd
from tests.g2.helpers import account, dept


def hr_history_rows():
    """2025-12 至 2026-11：培训费 2025-12 30,000.00；2026-01～11 合计 390,000.00（其中 2026-04 35,000.00）。"""
    rows = [kd("2025-12", "6602.03", "管理费用-培训费", "30000", dept="人力资源部")]
    for m in range(1, 12):
        rows.append(kd(f"2026-{m:02d}", "6602.03", "管理费用-培训费", "35000" if m == 4 else "35500", dept="人力资源部"))
    for p in ["2025-12", *[f"2026-{m:02d}" for m in range(1, 12)]]:
        rows.append(kd(p, "6602.01", "管理费用-工资", "150000", dept="人力资源部"))
    return rows


def prepare(ctx):
    task = ctx.publish(when="2026-12-01 10:00")
    ctx.import_kingdee(hr_history_rows(), "金蝶_2025-12至2026-11_利润表.xlsx")
    return task


def test_flow_16(seeded, client):
    db = seeded
    ctx = Ctx(db, client)
    task = prepare(ctx)
    ctx.now("2026-12-22 15:00")
    unit_id = ctx.unit(task, "人力资源部")
    train, care, hr = account(db, "培训费").id, account(db, "员工关怀费").id, dept(db, "人力资源部").id
    ctx.login("zhengke")
    ctx.save_ok(f"/api/filling-units/{unit_id}", [(f"de:{train}|amount", "2027-04", "50,000.00")])
    g = ctx.grid(f"/api/dept-expense/{unit_id}/grid")
    v = lambda key: next(r for r in g["rows"] if r["key"] == key)["values"]  # noqa: E731
    assert len([c for c in g["columns"] if c["kind"] == "value" and c["key"].startswith("2027-")]) == 12
    assert v(f"de:{train}|amount")["2027-04"] == "50,000.00"
    assert v(f"de:{train}|prior")["2027-04"] == "35,000.00"
    assert v(f"de:{train}|amount")["recent12"] == "420,000.00"
    assert v(f"de:{care}|amount")["recent12"] == "无历史数据"

    r = client.post("/api/reserves", json={"department_id": hr, "name": "管理层领导力训练营", "account_id": train,
                                           "plan_month": "2027-04", "amount": "180000.00"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    g = ctx.grid(f"/api/filling-units/{unit_id}/grid")
    assert next(r for r in g["rows"] if r["key"] == f"de:{train}|subtotal")["values"]["2027-04"] == "230,000.00"
    lst = client.get("/api/reserves", params={"department_id": hr}).json()
    assert [x["name"] for x in lst["reserves"]] == ["管理层领导力训练营"]
    assert lst["prior_label"] == "上年同科目实际（2026-01～11，12 月未导入）"
    assert lst["reserves"][0]["prior_year_actual_display"] == "390,000.00"

    ctx.now("2027-05-12 09:30")
    ctx.login("chensiyu")
    r = client.post(f"/api/reserves/{rid}/usages",
                    json={"amount": "96,000.00", "used_on": "2027-04-22", "voucher_no": "记-2027-04-0233"})
    assert r.status_code == 201, r.text
    assert (r.json()["used_display"], r.json()["remaining_display"]) == ("96,000.00", "84,000.00")
