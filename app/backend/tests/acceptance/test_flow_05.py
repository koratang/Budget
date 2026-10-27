"""FLOW-05 验收（单元 + API 层，真实路由 + 数据库）：期望值逐字取自 TDD验收契约 FLOW-05。

陈思雨上传 SKU 对照表，第 18 行（FM-2416-WH）缺品类、第 203 行（LM-4032-LED）缺首次上架日期 → 整份不写入（行数不变），
清单列出「18 · 缺少品类」「203 · 缺少首次上架日期」；修正后写入成功；SPU-FM-2416 首次上架 2026-03-15、SPU-MC-3026 2026-03-31；
判定：SPU-FM-2416 在 2027-02 为新品、2027-03 为老品；SPU-MC-3026 在 2027-03 为老品。
"""
from datetime import date

from app.calc.formulas import is_new_product
from app.services.masterdata import sku_count
from tests.acceptance.e1_helpers import XLSX, People, xlsx

HEADER = ["SKU", "SPU 编码", "品类", "首次上架日期"]


def sku_rows(fixed: bool) -> list[list]:
    """Excel 第 1 行为表头；第 2–210 行数据。第 18 行 FM-2416-WH 缺品类、第 203 行 LM-4032-LED 缺首次上架日期。"""
    rows = []
    for excel_row in range(2, 211):
        if excel_row == 17:
            rows.append(["FM-2416-BK", "SPU-FM-2416", "框镜", "2026-03-15"])
        elif excel_row == 18:
            rows.append(["FM-2416-WH", "SPU-FM-2416", "框镜" if fixed else None, "2026-04-02"])
        elif excel_row == 19:
            rows.append(["MC-3026-GY", "SPU-MC-3026", "镜柜", "2026-03-31"])
        elif excel_row == 203:
            rows.append(["LM-4032-LED", "SPU-LM-4032", "灯镜", "2026-05-20" if fixed else None])
        else:
            rows.append([f"BC-{excel_row:04d}-WH", f"SPU-BC-{excel_row // 4:03d}", "浴室柜", "2025-06-01"])
    return rows


def _judge(c, month, spu):
    items = c.get("/api/master/sku-mapping", params={"month": month, "q": spu}).json()["items"]
    verdicts = {r["is_new"] for r in items if r["spu"] == spu}
    assert len(verdicts) == 1, items
    return "新品" if verdicts.pop() else "老品"


def test_flow_05_rule():
    assert is_new_product(date(2027, 2, 1), date(2026, 3, 15)) is True     # 2027-02-28 早于 2027-03-15
    assert is_new_product(date(2027, 3, 1), date(2026, 3, 15)) is False    # 2027-03-31 不早于 2027-03-15
    assert is_new_product(date(2027, 3, 1), date(2026, 3, 31)) is False    # 2027-03-31 不早于 2027-03-31


def test_flow_05_upload_and_judge(seeded, dingtalk, tmp_path):
    db = seeded
    bp = People(db, dingtalk, tmp_path)("chensiyu")
    before = sku_count(db)
    r = bp.post("/api/master/sku-mapping/upload",
                files={"file": ("SKU对照表_2027-05.xlsx", xlsx(HEADER, sku_rows(False)), XLSX)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert [f"{i['row']} · {i['message']}" for i in body["issues"]] == ["18 · 缺少品类", "203 · 缺少首次上架日期"]
    assert sku_count(db) == before
    assert bp.post(f"/api/master/sku-mapping/upload/{body['id']}/confirm").status_code == 409
    assert sku_count(db) == before

    r = bp.post("/api/master/sku-mapping/upload",
                files={"file": ("SKU对照表_2027-05_修正.xlsx", xlsx(HEADER, sku_rows(True)), XLSX)})
    body = r.json()
    assert body["status"] == "passed" and body["issues"] == []
    r = bp.post(f"/api/master/sku-mapping/upload/{body['id']}/confirm")
    assert r.status_code == 200 and r.json()["status"] == "imported"
    assert sku_count(db) == before + 209
    for spu, first in (("SPU-FM-2416", "2026-03-15"), ("SPU-MC-3026", "2026-03-31")):
        items = bp.get("/api/master/sku-mapping", params={"month": "2027-03", "q": spu}).json()["items"]
        assert {x["spu_first_listed_on"] for x in items} == {first}
    assert _judge(bp, "2027-02", "SPU-FM-2416") == "新品"
    assert _judge(bp, "2027-03", "SPU-FM-2416") == "老品"
    assert _judge(bp, "2027-03", "SPU-MC-3026") == "老品"
