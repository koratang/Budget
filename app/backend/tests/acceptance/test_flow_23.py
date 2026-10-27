"""FLOW-23 BI 导入（REQ-F09-02、AC-F09-05/06/08/09）：真实路由 + 数据库。期望值逐字取自 TDD验收契约.md FLOW-23。"""
from datetime import date

from sqlalchemy import func, select

from app.models import BiActualAgg, BiActualSku, ImportBatch
from app.models.enums import ImportStatus
from tests.g3.conftest import g3  # noqa: F401
from tests.g3.fixtures_g3 import fixture_path


def _counts(db):
    return (db.scalar(select(func.count()).select_from(BiActualSku)),
            db.scalar(select(func.count()).select_from(BiActualAgg)))


def test_flow_23(g3):  # noqa: F811
    db = g3.db
    g3.add_skus()
    g3.set_now("2027-04-20 09:30")
    prior = g3.import_file(fixture_path("BI_2027-03_销售明细.xlsx"), "bi")      # 2027-03 已有 BI 数据
    g3.set_now("2027-05-06 14:00")
    before = _counts(db)

    # 首次上传整份不写入：全部未映射 SKU（2 个）及月份格式、站点不存在的行号与名称
    bad = g3.upload(fixture_path("BI_2027-03至04_销售明细.xlsx"), "bi")
    assert bad["status"] == "failed"
    assert sorted(bad["unmapped_skus"]) == ["BT-1701-WH", "SD-9999-XX"]
    by = {(i["type"], i["name"]): i["row"] for i in bad["issues"]}
    assert by[("月份格式错误", "2027-4")] == 40
    assert by[("站点不在主数据中", "墨西哥")] == 41
    assert {k[1] for k in by if k[0] == "SKU 未映射"} == {"BT-1701-WH", "SD-9999-XX"}
    assert _counts(db) == before

    # 修正后上传：覆盖前列出受影响月份与旧批次文件名、导入人、时间
    fixed = g3.upload(fixture_path("BI_2027-02至03_销售明细_v2.xlsx"), "bi")
    assert fixed["status"] == "passed" and fixed["needs_overwrite"] is True
    assert fixed["overwrite"] == [{"periods": ["2027-03"], "file_name": "BI_2027-03_销售明细.xlsx",
                                   "imported_by": "陈思雨", "imported_at": "2027-04-20 09:30"}]
    r = g3.confirm(fixed["id"], overwrite=True)
    assert r.status_code == 200, r.text

    # FM-2416-WH：2027-02 行 →「2027-02 × 店铺 × 站点 × 框镜 × 新品」；2027-03 行 →「× 老品」
    store, frame = g3.store("Amazon-US-01"), g3.category("框镜").id
    kids = {c.period: c for c in db.scalars(select(ImportBatch).where(ImportBatch.parent_batch_id == fixed["id"]))}
    feb = db.scalar(select(BiActualAgg).where(BiActualAgg.batch_id == kids[date(2027, 2, 1)].id,
                                              BiActualAgg.store_id == store.id, BiActualAgg.category_id == frame))
    mar = db.scalar(select(BiActualAgg).where(BiActualAgg.batch_id == kids[date(2027, 3, 1)].id,
                                              BiActualAgg.store_id == store.id, BiActualAgg.category_id == frame))
    assert (feb.month, feb.store_id, feb.site_id, feb.is_new) == (date(2027, 2, 1), store.id, store.site_id, True)
    assert (mar.month, mar.store_id, mar.site_id, mar.is_new) == (date(2027, 3, 1), store.id, store.site_id, False)

    # 确认后旧 BI 批次状态「已被替换」且记录保留
    assert db.get(ImportBatch, prior["id"]).status == ImportStatus.REPLACED
    rec = next(x for x in g3.client("陈思雨").get("/api/imports").json()["records"] if x["id"] == prior["id"])
    assert (rec["status_label"], rec["file_name"], rec["imported_by"], rec["imported_at"]) == \
        ("已被替换", "BI_2027-03_销售明细.xlsx", "陈思雨", "2027-04-20 09:30")
