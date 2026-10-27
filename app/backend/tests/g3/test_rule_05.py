"""RULE-05 导入整份拒绝与覆盖保留（DEC-008、AC-F09-01/03/05/08/09）。期望值逐字取自 TDD验收契约.md RULE-05 行。

本组覆盖金蝶与 BI；SKU 对照表上传（G1）与填报模板上传（G2）的同一断言由各自组的导入实现承担。
"""
from datetime import date

import pytest
from sqlalchemy import func, select, text

from app.models import Alert, ImportBatch, KingdeeActual, NotificationOutbox
from app.models.enums import ImportStatus
from app.services import alerting
from app.services.versions import actual_monthly
from tests.g3.fixtures_g3 import fixture_path

BUSINESS_TABLES = ["kingdee_actual", "bi_actual_sku", "bi_actual_agg", "alert", "notification_outbox", "platform_unit",
                   "b2b_unit", "dept_expense", "sku", "spu", "store", "budget_account", "kingdee_account_map"]


def snapshot(db):
    """各业务表行数与校验和（整行文本的 md5 聚合）。"""
    out = {}
    for t in BUSINESS_TABLES:
        out[t] = tuple(db.execute(text(
            f"SELECT count(*), coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '') FROM {t} x")).one())
    return out


def test_rule_05_reject_whole_file_and_keep_replaced(g3, monkeypatch):
    db = g3.db
    g3.add_skus()
    g3.set_now("2027-05-10 16:42")
    first = g3.import_file(fixture_path("金蝶_2027-04_利润表.xlsx"), "kingdee")
    g3.set_now("2027-05-12 10:00")

    # 只在最后一行出错的金蝶与 BI 文件：上传前后全部业务表行数与校验和不变
    before = snapshot(db)
    k = g3.upload(fixture_path("金蝶_2027-04_末行出错.xlsx"), "kingdee")
    b = g3.upload(fixture_path("BI_2027-04_末行出错.xlsx"), "bi")
    assert (k["status"], [i["row"] for i in k["issues"]]) == ("failed", [35])
    assert (b["status"], b["unmapped_skus"]) == ("failed", ["XX-0000-ZZ"])
    assert snapshot(db) == before

    # 覆盖导入时在确认事务中注入数据库错误 → 整个确认回滚
    fixed = g3.upload(fixture_path("金蝶_2027-04_利润表_v3.xlsx"), "kingdee")
    db.commit()

    def boom(session, *args, **kwargs):
        session.execute(text("SELECT 1 / 0"))

    monkeypatch.setattr(alerting, "evaluate", boom)
    with pytest.raises(Exception, match="division by zero"):
        g3.confirm(fixed["id"], overwrite=True)
    db.expire_all()
    assert db.get(ImportBatch, first["id"]).status == ImportStatus.EFFECTIVE
    assert db.get(ImportBatch, fixed["id"]).status == ImportStatus.PENDING_CONFIRM
    assert db.scalar(select(func.count()).select_from(ImportBatch).where(
        ImportBatch.parent_batch_id == fixed["id"])) == 0
    assert db.scalar(select(func.count()).select_from(Alert)) == 0
    assert db.scalar(select(func.count()).select_from(NotificationOutbox)) == 0
    assert snapshot(db) == before

    # 正常完成覆盖：旧批次行仍在库、状态「已被替换」且不参与任何计算；导入记录保留
    monkeypatch.undo()
    r = g3.confirm(fixed["id"], overwrite=True)
    assert r.status_code == 200, r.text
    db.expire_all()
    old_child = db.scalar(select(ImportBatch).where(ImportBatch.parent_batch_id == first["id"]))
    assert old_child.status == ImportStatus.REPLACED and db.get(ImportBatch, first["id"]).status == ImportStatus.REPLACED
    assert db.scalar(select(func.count()).select_from(KingdeeActual).where(KingdeeActual.batch_id == old_child.id)) == 34
    revenue = actual_monthly(db, [date(2027, 4, 1)])[date(2027, 4, 1)].revenue
    # 修正文件收入合计（原文件 Amazon-US-01 为 530,000.00，修正后为 535,000.00；旧行不计入）
    assert revenue == 535000 + 355000 + 98000 + 120000 + 210000 + 86000 + 64000 + 230000 + 76000 + 42000
    rec = next(x for x in g3.client("陈思雨").get("/api/imports").json()["records"] if x["id"] == first["id"])
    assert (rec["file_name"], rec["imported_by"], rec["imported_at"], rec["status_label"]) == \
        ("金蝶_2027-04_利润表.xlsx", "陈思雨", "2027-05-10 16:42", "已被替换")
