"""FLOW-19 季度目标调整（API 层验收，真实路由 + 数据库）。期望值逐字取自 TDD验收契约.md FLOW-19：

2027-04 单元保存被拒并提示「该月已导入实际，不能调整」，2027-06 可保存；无原因提交提示「请填写调整原因」；
CEO 通过后版本列表新增「调整后目标」V3，记录版本号 V3、审批人周明远、审批时间与调整原因；
V1 与 V2 全部单元值与调整前逐值相同；再次发起被阻止且「发起季度调整」按钮显示不可用原因

前置（契约初始状态）：V1 经完整编制审批生成；V2 为 Q1 经 CEO 通过的调整；金蝶实际经导入接口导入至 2027-04。
编辑走填报表格调整模式的同一保存接口 PATCH /api/filling-units/{id}/cells（与界面一致），不在服务层模拟。
"""
from sqlalchemy import select

from app.models import AuditLog, BudgetVersion, FillingUnit, PlatformUnit
from tests.acceptance.e2_common import Ctx, actual_rows_2027
from tests.g2.helpers import pu_key

REASON = "Prime Day 提前至 6 月，7 月部分销量前移至 6 月"


def version_rows(db, version_id):
    db.expire_all()
    return [(u.store_id, u.category_id, u.is_new, u.month, u.spu_count, u.avg_sales, u.avg_price, u.revenue_cny,
             u.gross_profit)
            for u in db.scalars(select(PlatformUnit).where(PlatformUnit.version_id == version_id)
                                .order_by(PlatformUnit.id))]


def prepare(ctx: Ctx) -> dict:
    db = ctx.db
    v1 = ctx.build_v1()
    k = lambda item: pu_key(db, "Amazon-US-01", "浴室柜", False, item)  # noqa: E731
    ctx.run_adjustment("2027-02-10 10:00", {"Amazon-US-01": [(k("avg_sales"), "2027-03", "70")]},
                       "Q1 下调 Amazon-US-01 3 月销量", "2027-02-20 10:00")
    v2 = db.scalar(select(BudgetVersion.id).where(BudgetVersion.type == "adjusted_target"))
    ctx.now("2027-05-10 16:00")
    ctx.import_kingdee(actual_rows_2027([1, 2, 3, 4]), "金蝶_2027-01至04_利润表.xlsx")
    return {"v1": v1, "v2": v2}


def test_flow_19_quarter_adjustment(seeded, client):
    db = seeded
    ctx = Ctx(db, client)
    pre = prepare(ctx)
    before_v1, before_v2 = version_rows(db, pre["v1"]), version_rows(db, pre["v2"])
    assert before_v1 and before_v2 and before_v1 != before_v2

    # 2027-05-12 林晓发起 2027 Q2 目标调整
    ctx.now("2027-05-12 09:00")
    ctx.login("linxiao")
    page = client.get("/api/versions").json()
    assert page["actual_through"] == "2027-04" and page["actions"]["adjust"]["enabled"] is True
    r = client.post("/api/versions/adjustments")
    assert r.status_code == 200, r.text
    adj_id = r.json()["id"]

    # 王浩在「我的填报」看到调整单位并以调整模式编辑
    ctx.login("wanghao")
    mine = client.get("/api/filling-units?mine=1").json()["items"]
    unit = next(u for u in mine if u["adjustment"] and u["name"] == "Amazon-US-01")
    base = f"/api/filling-units/{unit['id']}"
    key = pu_key(db, "Amazon-US-01", "浴室柜", False, "avg_sales")
    g = ctx.grid(f"{base}/grid")
    row = next(x for x in g["rows"] if x["key"] == key)
    assert "2027-04" in row["readonly_fields"] and "2027-06" not in row["readonly_fields"]
    r = ctx.save(base, [(key, "2027-04", "80")])
    assert r.status_code == 200
    assert [e["message"] for e in r.json()["errors"]] == ["该月已导入实际，不能调整"]
    r = ctx.save(base, [(key, "2027-06", "90")])
    assert r.status_code == 200 and r.json()["errors"] == [], r.text
    vals = next(x for x in r.json()["grid"]["rows"] if x["key"] == key)["values"]
    assert vals["2027-06"] in ("90", "90.0", "90.00", "90.0000") and vals["2027-04"] != "80"

    # 先不填调整原因提交 → 「请填写调整原因」；再填原因提交
    r = client.post(f"{base}/submit", json={"adjust_reason": ""})
    assert r.status_code == 422 and r.json()["message"] == "请填写调整原因"
    r = client.post(f"{base}/submit", json={"adjust_reason": REASON})
    assert r.status_code == 200 and r.json()["status"] == "submitted", r.text

    units = list(db.scalars(select(FillingUnit).where(FillingUnit.adjustment_id == adj_id).order_by(FillingUnit.id)))
    for u in units:
        if u.id == unit["id"]:
            continue
        ctx.login(ctx.userid_of(u.filler_id))
        r = client.post(f"/api/filling-units/{u.id}/submit", json={"adjust_reason": "本单位无调整"})
        assert r.status_code == 200, r.text

    # 赵磊、林晓逐级通过全部单位
    ctx.login("zhaolei")
    pending = client.get("/api/approvals").json()["items"]
    assert ("adjustment-unit", unit["id"]) in [(i["type"], i["id"]) for i in pending]
    ctx.approve_adjustment_units(units)
    ctx.login("zhoumingyuan")
    assert [(i["type"], i["id"]) for i in client.get("/api/approvals").json()["items"]] == [("adjustment", adj_id)]

    # 周明远整次通过 → V3
    ctx.now("2027-05-12 16:30")
    ctx.login("zhoumingyuan")
    r = client.post(f"/api/approvals/adjustment/{adj_id}/approve")
    assert r.status_code == 200, r.text
    ctx.login("linxiao")
    page = client.get("/api/versions").json()
    v3 = next(v for v in page["versions"] if v["label"] == "V3")
    assert v3["type_label"] == "调整后目标"
    assert v3["approver"].startswith("周明远")
    assert v3["time"] == "2027-05-12 16:30"
    assert REASON in v3["reason"]
    v3_row = db.get(BudgetVersion, v3["id"])
    assert v3_row.version_no == 3 and v3_row.adjust_reason and REASON in v3_row.adjust_reason

    # V1 与 V2 全部单元值与调整前逐值相同；V3 中 2027-06 为调整后的值
    assert version_rows(db, pre["v1"]) == before_v1
    assert version_rows(db, pre["v2"]) == before_v2

    # 同一季度再次发起被阻止，按钮显示不可用原因
    r = client.post("/api/versions/adjustments")
    assert r.status_code == 409
    expected = "本季度已有一次经 CEO 审批通过的目标调整（V3，2027-05-12），2027-07-01 起可发起下季度调整"
    assert r.json()["message"] == expected
    assert client.get("/api/versions").json()["actions"]["adjust"] == {"enabled": False, "reason": expected}

    # NFR-004：发起、提交、各级审批、生效均有审计
    acts = set(db.scalars(select(AuditLog.action)))
    assert {"adjustment_started", "adjustment_unit_submitted", "adjustment_unit_approved", "adjustment_pending_ceo",
            "adjustment_effective"} <= acts
