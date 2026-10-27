"""FLOW-20 季度滚动预测与快照（AC-F08-05~07、AC-F08-09）。期望值逐字取自 TDD验收契约.md FLOW-20 行。

本机用开发身份与钉钉替身；填报表格只开放月份由 versions.open_months() 给出（G2 表格据此锁定），
填报人保存驱动以直接写入滚动预测稿的单元派生值模拟。
"""
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import BudgetVersion, NotificationOutbox, PlatformUnit, User, UserRole
from app.models.enums import Role, VersionType
from app.services import versions as svc
from tests.g3.fixtures_g3 import KINGDEE_HEADER, kd, write_xlsx


def test_flow_20_rolling_forecast(g3):
    db = g3.db
    g3.set_now("2026-12-28 17:30")
    v1 = g3.make_version(stores={"Amazon-US-01": {m: (600000, 150000) for m in range(1, 13)},
                                 "Wayfair-US-01": {m: (300000, 60000) for m in range(1, 13)}},
                         depts={"人力资源部": 1200000})

    # 2027-01-08 以年初原始目标发布 Q1 快照：逐月数值与 V1 相同，无需填报人提交
    g3.set_now("2027-01-08 10:00")
    page = g3.client("林晓").get("/api/versions").json()
    assert page["actions"]["publish_original"]["visible"] is True
    r = g3.client("林晓").post("/api/versions/rolling/publish-original")
    assert r.status_code == 200, r.text
    q1 = r.json()["id"]
    s_q1 = g3.client("林晓").get(f"/api/versions/{q1}/summary").json()["months"]
    s_v1 = g3.client("林晓").get(f"/api/versions/{v1.id}/summary").json()["months"]
    assert [(m["month"], m["revenue"], m["gross"], m["net"]) for m in s_q1] == \
        [(m["month"], m["revenue"], m["gross"], m["net"]) for m in s_v1]

    # 2027-04-22 发起 Q2 滚动更新：运营、B端业务、物流物控、财务BP 各收到工作通知
    g3.set_now("2027-04-22 09:00")
    r = g3.client("林晓").post("/api/versions/rolling")
    assert r.status_code == 200, r.text
    draft_id = r.json()["id"]
    box = db.scalar(select(NotificationOutbox).where(NotificationOutbox.biz_type == "rolling_started"))
    for role in (Role.OPERATIONS, Role.B2B, Role.LOGISTICS, Role.FINANCE_BP):
        ids = db.scalars(select(User.dingtalk_userid).join(UserRole, UserRole.user_id == User.id)
                         .where(UserRole.role_code == role))
        assert set(ids) <= set(box.receivers), role
    # 只开放 4–12 月，1–3 月不可编辑
    assert svc.open_months(db, draft_id) == {date(2027, m, 1) for m in range(4, 13)}
    assert g3.client("林晓").post("/api/versions/rolling").status_code == 409   # 同一季度只发起一次

    # 填报人更新 5–12 月驱动（Amazon-US-01 驱动计算值 4 月 ¥ 600,000.00，5–12 月改为 ¥ 650,000.00）
    store = g3.store("Amazon-US-01")
    for u in db.scalars(select(PlatformUnit).where(PlatformUnit.version_id == draft_id,
                                                   PlatformUnit.store_id == store.id,
                                                   PlatformUnit.month >= date(2027, 5, 1))):
        u.revenue_cny, u.gross_profit = 650000, 162500
    db.flush()
    units = g3.client("林晓").get(f"/api/versions/rolling/{draft_id}").json()["units"]
    last = units[-1]
    for u in units[:-1]:
        filler = db.get(User, u["filler_id"]).name
        r = g3.client(filler).post(f"/api/versions/rolling/{draft_id}/units/{u['key']}/submit")
        assert r.status_code == 200, r.text
    # 仍有未提交者：发布返回名单供确认
    r = g3.client("林晓").post(f"/api/versions/rolling/{draft_id}/publish", json={})
    assert r.status_code == 409 and r.json()["details"]["units"][0]["name"] == last["name"]
    filler = db.get(User, last["filler_id"]).name
    assert g3.client(filler).post(f"/api/versions/rolling/{draft_id}/units/{last['key']}/submit").status_code == 200

    # 金蝶 2027-04 实际已导入：Amazon-US-01 实际收入 ¥ 554,400.00
    g3.set_now("2027-05-10 16:00")
    path = write_xlsx(g3.tmp / "金蝶_2027-04_利润表.xlsx", KINGDEE_HEADER, [
        kd("2027-04", "收入", 554400, store="Amazon-US-01", site="美国"),
        kd("2027-04", "采购", 194040, store="Amazon-US-01", site="美国"),
        kd("2027-04", "收入", 280000, store="Wayfair-US-01", site="美国"),
        kd("2027-04", "工资", 100000, dept="人力资源部")])
    g3.import_file(path, "kingdee")

    # 林晓发布 Q2 快照
    g3.set_now("2027-05-12 10:00")
    r = g3.client("林晓").post(f"/api/versions/rolling/{draft_id}/publish", json={})
    assert r.status_code == 200, r.text
    assert (r.json()["quarter_label"], r.json()["published_on"]) == ("2027 Q2", "2027-05-12")
    months = g3.client("林晓").get(f"/api/versions/{draft_id}/summary",
                                  params={"store_id": store.id}).json()["months"]
    by = {m["month"]: m for m in months}
    assert (by["2027-04"]["revenue"], by["2027-04"]["revenue_display"], by["2027-04"]["source"]) == \
        ("554400", "¥ 554,400.00", "actual")
    assert all((by[f"2027-{m:02d}"]["revenue"], by[f"2027-{m:02d}"]["source"]) == ("650000", "forecast")
               for m in range(5, 13))
    row = next(v for v in g3.client("林晓").get("/api/versions").json()["versions"] if v["id"] == draft_id)
    assert (row["label"], row["quarter_label"], row["published_on"], row["status_label"]) == \
        ("Q2 快照", "2027 Q2", "2027-05-12", "不可修改")
    assert row["reason"] == "1–4 月实际 + 5–12 月最新提交驱动"

    # 修改被拒：接口与数据库触发器
    assert g3.client("林晓").post(f"/api/versions/rolling/{draft_id}/publish", json={}).status_code == 409
    snap = db.get(BudgetVersion, draft_id)
    assert snap.type == VersionType.SNAPSHOT and snap.locked
    with pytest.raises(DBAPIError) as e:
        with db.begin_nested():
            db.execute(text("UPDATE platform_unit SET revenue_cny = 1 WHERE version_id = :v"), {"v": draft_id})
    assert "版本已锁定，不能修改" in str(e.value)
