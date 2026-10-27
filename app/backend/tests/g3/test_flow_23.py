"""FLOW-23 BI 双月导入：SKU 未映射 / 月份格式 / 站点不存在整份拒绝；按品类 × 新老品归集；多月份覆盖确认
（AC-F09-05、AC-F09-06、AC-F09-08、AC-F09-09）。期望值逐字取自 TDD验收契约.md FLOW-23 行。"""
from datetime import date

from sqlalchemy import func, select

from app.models import BiActualAgg, BiActualSku, ImportBatch
from app.models.enums import ImportStatus
from tests.g3.fixtures_g3 import fixture_path


def _counts(db):
    return (db.scalar(select(func.count()).select_from(BiActualSku)),
            db.scalar(select(func.count()).select_from(BiActualAgg)))


def test_flow_23_bi_import(g3):
    db = g3.db
    g3.add_skus()
    # 前置：2027-03 已有 BI 数据
    g3.set_now("2027-04-20 09:30")
    prior = g3.import_file(fixture_path("BI_2027-03_销售明细.xlsx"), "bi")
    g3.set_now("2027-05-06 14:00")
    before = _counts(db)

    # 1. 首次上传整份不写入：未映射 SKU 2 个 + 第 40 行月份「2027-4」+ 第 41 行站点「墨西哥」
    bad = g3.upload(fixture_path("BI_2027-03至04_销售明细.xlsx"), "bi")
    assert bad["status"] == "failed"
    assert sorted(bad["unmapped_skus"]) == ["BT-1701-WH", "SD-9999-XX"]
    by_type = {(i["type"], i["name"]): i["row"] for i in bad["issues"]}
    assert by_type[("月份格式错误", "2027-4")] == 40
    assert by_type[("站点不在主数据中", "墨西哥")] == 41
    assert by_type[("SKU 未映射", "BT-1701-WH")] == "第 6 行起 · 共 1 行"
    assert by_type[("SKU 未映射", "SD-9999-XX")] == "第 11 行起 · 共 2 行"
    assert _counts(db) == before

    # 2. 修正后上传：覆盖前列出受影响月份与旧批次文件名、导入人、时间
    fixed = g3.upload(fixture_path("BI_2027-02至03_销售明细_v2.xlsx"), "bi")
    assert fixed["status"] == "passed"
    assert fixed["periods"] == ["2027-02", "2027-03"]
    assert fixed["needs_overwrite"] is True
    assert fixed["overwrite"] == [{"periods": ["2027-03"], "file_name": "BI_2027-03_销售明细.xlsx",
                                   "imported_by": "陈思雨", "imported_at": "2027-04-20 09:30"}]
    preview = {(p["month"], p["store"], p["category"], p["is_new_label"]) for p in fixed["summary"]["preview"]}
    assert ("2027-02", "Amazon-US-01", "框镜", "新品") in preview
    assert ("2027-03", "Amazon-US-01", "框镜", "老品") in preview
    assert g3.confirm(fixed["id"], overwrite=False).status_code == 409
    r = g3.confirm(fixed["id"], overwrite=True)
    assert r.status_code == 200, r.text

    # 3. FM-2416-WH（SPU-FM-2416，框镜，首次上架 2026-03-15）：2027-02 → 新品，2027-03 → 老品
    store = g3.store("Amazon-US-01")
    frame = g3.category("框镜").id
    children = {c.period: c for c in db.scalars(select(ImportBatch).where(ImportBatch.parent_batch_id == fixed["id"]))}
    feb = db.scalar(select(BiActualAgg).where(BiActualAgg.batch_id == children[date(2027, 2, 1)].id,
                                              BiActualAgg.store_id == store.id, BiActualAgg.category_id == frame))
    mar = db.scalar(select(BiActualAgg).where(BiActualAgg.batch_id == children[date(2027, 3, 1)].id,
                                              BiActualAgg.store_id == store.id, BiActualAgg.category_id == frame))
    assert (feb.month, feb.site_id, feb.is_new, feb.spu_count) == (date(2027, 2, 1), store.site_id, True, 1)
    assert (mar.month, mar.is_new) == (date(2027, 3, 1), False)

    # 4. 旧 BI 批次「已被替换」，记录保留（文件名、导入人、时间）
    assert db.get(ImportBatch, prior["id"]).status == ImportStatus.REPLACED
    rec = next(x for x in g3.client("陈思雨").get("/api/imports").json()["records"] if x["id"] == prior["id"])
    assert (rec["file_name"], rec["imported_by"], rec["imported_at"], rec["status_label"]) == \
        ("BI_2027-03_销售明细.xlsx", "陈思雨", "2027-04-20 09:30", "已被替换")
    old_child = db.scalar(select(ImportBatch).where(ImportBatch.parent_batch_id == prior["id"]))
    assert db.scalar(select(func.count()).select_from(BiActualSku).where(BiActualSku.batch_id == old_child.id)) == 3
