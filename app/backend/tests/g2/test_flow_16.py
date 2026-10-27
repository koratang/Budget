"""FLOW-16：部门费用填报、历史参考与专项预留额度（AC-F05-01~05）。

契约期望：填报按「预算科目 × 月」提供人民币金额；培训费 2027-04 单元下显示上年同月实际 35,000.00，行尾「近 12 月实际合计」
420,000.00，员工关怀费行显示「无历史数据」；新增专项后培训费 2027-04 预算变为 230,000.00 且专项列表出现该专项，
专项行「上年同科目实际（2026-01～11，12 月未导入）」显示 390,000.00；登记后已用 96,000.00、剩余 84,000.00
"""
from datetime import date, datetime
from decimal import Decimal

from app.core.clock import TZ, clock
from app.models import ImportBatch, KingdeeActual
from tests.g2.helpers import account, dept, grid, login, minimal_units, publish, row, save, uid, unit_by_name


def import_hr_history(db):
    """已导入 2025-12 至 2026-11 金蝶实际：培训费 2025-12 30,000.00，2026-01～11 合计 390,000.00（其中 2026-04 35,000.00）。"""
    hr, train, salary = dept(db, "人力资源部").id, account(db, "培训费").id, account(db, "工资薪酬").id
    batch = ImportBatch(source="kingdee-history", file_name="金蝶_2025-12至2026-11_历史利润表.xlsx",
                        status="effective", uploaded_by=uid(db, "chensiyu"))
    db.add(batch)
    db.flush()
    amounts = {date(2025, 12, 1): Decimal("30000.00"), date(2026, 4, 1): Decimal("35000.00")}
    for m in (1, 2, 3, 5, 6, 7, 8, 9, 10, 11):
        amounts[date(2026, m, 1)] = Decimal("35500.00")  # 10 个月 355,000.00 + 4 月 35,000.00 = 390,000.00
    for month, amount in amounts.items():
        db.add(KingdeeActual(batch_id=batch.id, month=month, department_id=hr, kingdee_code="6602.03",
                             account_id=train, amount=amount))
        db.add(KingdeeActual(batch_id=batch.id, month=month, department_id=hr, kingdee_code="6602.01",
                             account_id=salary, amount=Decimal("150000.00")))
    db.flush()


def test_flow_16_dept_expense_history_and_reserves(seeded, client):
    db = seeded
    clock.set_now(datetime(2026, 12, 1, 10, 0, tzinfo=TZ))
    task_id = publish(client, db, minimal_units(db)).json()["task"]["id"]
    import_hr_history(db)
    clock.set_now(datetime(2026, 12, 22, 15, 0, tzinfo=TZ))
    unit_id = unit_by_name(db, task_id, "人力资源部").id
    train, care = account(db, "培训费").id, account(db, "员工关怀费").id

    login(client, db, "zhengke")
    assert client.get("/api/dept-expense/my-unit").json() == {"unit_id": unit_id}
    r = save(client, unit_id, [(f"de:{train}|amount", "2027-04", "50,000.00")])
    assert r.json()["errors"] == [], r.text
    g = client.get(f"/api/dept-expense/{unit_id}/grid").json()
    months = [c["key"] for c in g["columns"] if c["kind"] == "value" and c["key"].startswith("2027-")]
    assert len(months) == 12  # 预算科目 × 月，人民币金额
    assert row(g, f"de:{train}|amount")["values"]["2027-04"] == "50,000.00"
    assert row(g, f"de:{train}|prior")["values"]["2027-04"] == "35,000.00"
    assert row(g, f"de:{train}|amount")["values"]["recent12"] == "420,000.00"
    assert row(g, f"de:{care}|amount")["values"]["recent12"] == "无历史数据"
    assert row(g, f"de:{care}|prior")["values"]["item"] == "无历史数据"

    r = client.post("/api/reserves", json={"department_id": dept(db, "人力资源部").id, "name": "管理层领导力训练营",
                                           "account_id": train, "plan_month": "2027-04", "amount": "180000.00"})
    assert r.status_code == 201, r.text
    reserve_id = r.json()["id"]
    g = grid(client, unit_id)
    assert row(g, f"de:{train}|subtotal")["values"]["2027-04"] == "230,000.00"
    lst = client.get("/api/reserves", params={"department_id": dept(db, "人力资源部").id}).json()
    assert [x["name"] for x in lst["reserves"]] == ["管理层领导力训练营"]
    assert lst["prior_label"] == "上年同科目实际（2026-01～11，12 月未导入）"
    assert lst["reserves"][0]["prior_year_actual_display"] == "390,000.00"

    # 2027-05-12 陈思雨登记使用
    clock.set_now(datetime(2027, 5, 12, 9, 30, tzinfo=TZ))
    login(client, db, "zhengke")
    r = client.post(f"/api/reserves/{reserve_id}/usages",
                    json={"amount": "96000", "used_on": "2027-04-22", "voucher_no": "记-2027-04-0233"})
    assert r.status_code == 403  # 只有财务BP 登记使用
    login(client, db, "chensiyu")
    r = client.post(f"/api/reserves/{reserve_id}/usages",
                    json={"amount": "96,000.00", "used_on": "2027-04-22", "voucher_no": "记-2027-04-0233"})
    assert r.status_code == 201, r.text
    assert r.json()["used_display"] == "96,000.00" and r.json()["remaining_display"] == "84,000.00"
    assert r.json()["usages"][0]["voucher_no"] == "记-2027-04-0233"
