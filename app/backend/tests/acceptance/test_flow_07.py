"""FLOW-07 验收（单元 + API 层，真实路由 + 数据库）：期望值逐字取自 TDD验收契约 FLOW-07。

编制期陈思雨录入 2027 USD 预算汇率 7.12 → Amazon-US-01 收入 USD 86,400.00 折人民币 ¥ 615,168.00；
Amazon-DE-01 结算币种 EUR 且 2027 无 EUR 预算汇率时王浩提交含该店铺的单位 → 被阻止并提示含「EUR」；
录入 2027-04 USD 当月平均汇率 7.2000 → 2027-04 BI 本币 USD 77,000.00 折人民币 ¥ 554,400.00；
CEO 锁定 2027 年初原始目标后：汇率页显示「已随年初原始目标锁定」，修改 USD 被拒（409、仍为 7.12），新增 JPY 成功。
"""
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.money import fmt_cny
from app.models import Category, FillingUnit, FxBudget, Store, UserScope
from tests.acceptance.e1_helpers import DEADLINE, KINGDEE_HEADER, XLSX, People, uid, xlsx

BI_HEADER = ["月份", "店铺", "站点", "SKU", "销量", "本币销售额", "币种", "广告费", "平台费用"]


def test_flow_07_unit():
    assert Decimal("86400.00") * Decimal("7.12") == Decimal("615168.0000")
    assert fmt_cny(Decimal("77000.00") * Decimal("7.2000")) == "¥ 554,400.00"


def _key(db, store, field, is_new=True):
    s = db.scalar(select(Store).where(Store.name == store))
    cat = db.scalar(select(Category.id).where(Category.name == "浴室柜"))
    return f"pu:{s.id}:{s.site_id}:{cat}:{1 if is_new else 0}|{field}"


def _save(c, unit_id, changes):
    g = c.get(f"/api/filling-units/{unit_id}/grid").json()
    base = {r["key"]: r["values"] for r in g["rows"]}
    body = [{"row_key": k, "field": f, "value": v, "base": base[k].get(f)} for k, f, v in changes]
    r = c.patch(f"/api/filling-units/{unit_id}/cells", json=body)
    assert r.status_code == 200 and r.json()["errors"] == [], r.text
    return r.json()


def test_flow_07(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    db.execute(delete(FxBudget).where(FxBudget.year == 2027, FxBudget.currency.in_(("USD", "EUR"))))
    us = db.scalar(select(Store.id).where(Store.name == "Amazon-US-01"))
    de = db.scalar(select(Store.id).where(Store.name == "Amazon-DE-01"))
    db.add(UserScope(user_id=uid(db, "wanghao"), scope_type="store", object_id=de))  # 前置：王浩负责含 DE 店铺的单位
    db.flush()
    bp, lin, wang = p("chensiyu"), p("linxiao"), p("wanghao")

    r = bp.put("/api/master/fx/budget", json={"year": 2027, "currency": "USD", "rate": "7.12"})
    assert r.status_code == 200, r.text
    cands = lin.get("/api/tasks/candidates").json()["items"]
    units = [{"unit_type": "platform", "scope_object_id": sid} for sid in (us, de)]
    assert {c["filler"]["name"] for c in cands if c["unit_type"] == "platform" and c["scope_object_id"] in (us, de)} \
        == {"王浩"}
    r = lin.post("/api/tasks", json={"year": 2027, "deadline": DEADLINE, "units": units})
    assert r.status_code == 201, r.text
    task_id = r.json()["task"]["id"]
    uids = {u.scope_object_id: u.id for u in db.scalars(select(FillingUnit).where(FillingUnit.task_id == task_id))}

    _save(wang, uids[us], [(_key(db, "Amazon-US-01", "spu_count"), "2027-03", "10"),
                                 (_key(db, "Amazon-US-01", "avg_sales"), "2027-03", "120"),
                                 (_key(db, "Amazon-US-01", "avg_price"), "2027-03", "80.00"),
                                 (_key(db, "Amazon-US-01", "discount_rate"), "2027-03", "10")])
    kpis = wang.get(f"/api/filling-units/{uids[us]}/grid").json()["kpis"]
    assert "86,400.00" in kpis["revenue_local_display"] and "USD" in kpis["revenue_local_display"], kpis
    assert kpis["revenue_cny_display"] == "¥ 615,168.00", kpis

    _save(wang, uids[de], [(_key(db, "Amazon-DE-01", "spu_count"), "2027-03", "2")])
    r = wang.post(f"/api/filling-units/{uids[de]}/submit")
    assert r.status_code in (409, 422), r.text
    assert "EUR" in r.json()["message"], r.json()
    assert db.get(FillingUnit, uids[de]).status != "submitted"

    # 2027-04 当月平均汇率与 BI 折算
    r = bp.put("/api/master/fx/actual", json={"month": "2027-04", "currency": "USD", "rate": "7.2000"})
    assert r.status_code == 200 and r.json()["rate"] == "7.2000"
    r = bp.post("/api/master/sku-mapping/upload", files={"file": ("SKU对照表.xlsx", xlsx(
        ["SKU", "SPU 编码", "品类", "首次上架日期"], [["BC-2201-WH", "SPU-BC-2201", "浴室柜", "2025-06-01"]]), XLSX)})
    assert bp.post(f"/api/master/sku-mapping/upload/{r.json()['id']}/confirm").status_code == 200
    for name, source, header, rows in (
            ("BI_2027-04_销售明细.xlsx", "bi", BI_HEADER,
             [["2027-04", "Amazon-US-01", "US", "BC-2201-WH", 1000, 77000.00, "USD", 5000, 9000]]),
            ("金蝶_2027-04_利润表.xlsx", "kingdee", KINGDEE_HEADER,
             [["2027-04", "6001", "主营业务收入", "运营部", "Amazon-US-01", "US", "", "", 550000]])):
        r = bp.post("/api/imports", files={"file": (name, xlsx(header, rows), XLSX)}, data={"source": source})
        b = bp.get(f"/api/imports/{r.json()['id']}").json()
        assert b["status"] == "passed", b
        assert bp.post(f"/api/imports/{b['id']}/confirm", json={"overwrite": False}).status_code == 200
    rec = bp.get("/api/reconciliation", params={"month": "2027-04"}).json()
    row = next(x for x in rec["rows"] if x["store"] == "Amazon-US-01")
    assert "77,000.00" in row["bi_local_display"] and row["currency"] == "USD", row
    assert row["rate"] == "7.2000" and row["bi_cny_display"] == "¥ 554,400.00", row

    # CEO 锁定年初原始目标
    assert bp.put("/api/master/fx/budget", json={"year": 2027, "currency": "EUR", "rate": "7.79"}).status_code == 200
    for sid in (us, de):
        assert wang.post(f"/api/filling-units/{uids[sid]}/submit").status_code == 200
        assert p("zhaolei").post(f"/api/approvals/unit/{uids[sid]}/approve").status_code == 200
    assert lin.post(f"/api/tasks/{task_id}/submit-to-ceo").status_code == 200
    assert p("zhoumingyuan").post(f"/api/approvals/task/{task_id}/approve").status_code == 200

    page = bp.get("/api/master/fx/budget", params={"year": 2027}).json()
    assert page["locked"] is True and page["lock_message"] == "已随年初原始目标锁定"
    r = bp.put("/api/master/fx/budget", json={"year": 2027, "currency": "USD", "rate": "7.20"})
    assert r.status_code == 409 and r.json()["message"] == "已随年初原始目标锁定"
    usd = next(i for i in bp.get("/api/master/fx/budget", params={"year": 2027}).json()["items"]
               if i["currency"] == "USD")
    assert Decimal(usd["rate"]) == Decimal("7.12")
    r = bp.put("/api/master/fx/budget", json={"year": 2027, "currency": "JPY", "rate": "0.0478"})
    assert r.status_code == 200, r.text
    assert db.scalar(select(FxBudget.rate).where(FxBudget.year == 2027, FxBudget.currency == "JPY")) == \
        Decimal("0.0478")
