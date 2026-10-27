"""FLOW-05 SKU 对照表与新老品判定（REQ-F02-02，AC-F02-03/04；DEC-021）：期望值逐字取自 TDD验收契约 FLOW-05。"""
from datetime import date

from app.calc.formulas import is_new_product
from app.services.masterdata import sku_count
from tests.g1.helpers import login, xlsx

HEADER = ["SKU", "SPU 编码", "品类", "首次上架日期"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _rows(fixed: bool) -> list[list]:
    """Excel 第 1 行为表头；第 18 行 FM-2416-WH 缺品类、第 203 行 LM-4032-LED 缺首次上架日期（修正后补齐）。"""
    rows = [HEADER]
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


def _upload(client, rows):
    files = {"file": ("SKU对照表_2027-05.xlsx", xlsx(rows), XLSX)}
    return client.post("/api/master/sku-mapping/upload", files=files)


def _judge(client, month, spu):
    data = client.get("/api/master/sku-mapping", params={"month": month, "q": spu}).json()
    verdicts = {r["is_new"] for r in data["items"] if r["spu"] == spu}
    assert len(verdicts) == 1
    return "新品" if verdicts.pop() else "老品"


def test_new_product_rule():
    assert is_new_product(date(2027, 2, 1), date(2026, 3, 15)) is True     # 2027-02-28 早于 2027-03-15
    assert is_new_product(date(2027, 3, 1), date(2026, 3, 15)) is False    # 2027-03-31 不早于 2027-03-15
    assert is_new_product(date(2027, 3, 1), date(2026, 3, 31)) is False    # 2027-03-31 不早于 2027-03-31


def test_sku_upload_rejects_whole_file_then_accepts_fixed(seeded, db, dingtalk):
    bp = login(db, dingtalk, "chensiyu")
    before = sku_count(db)
    r = _upload(bp, _rows(fixed=False))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert [f"{i['row']} · {i['message']}" for i in body["issues"]] == ["18 · 缺少品类", "203 · 缺少首次上架日期"]
    assert sku_count(db) == before
    assert bp.post(f"/api/master/sku-mapping/upload/{body['id']}/confirm").status_code == 409

    r = _upload(bp, _rows(fixed=True))
    body = r.json()
    assert body["status"] == "passed" and body["issues"] == [] and body["added"] == 209
    r = bp.post(f"/api/master/sku-mapping/upload/{body['id']}/confirm")
    assert r.status_code == 200 and r.json()["status"] == "imported"
    assert sku_count(db) == before + 209

    data = bp.get("/api/master/sku-mapping", params={"month": "2027-03", "q": "SPU-FM-2416"}).json()
    assert {r["spu_first_listed_on"] for r in data["items"]} == {"2026-03-15"}
    data = bp.get("/api/master/sku-mapping", params={"month": "2027-03", "q": "SPU-MC-3026"}).json()
    assert {r["spu_first_listed_on"] for r in data["items"]} == {"2026-03-31"}

    assert _judge(bp, "2027-02", "SPU-FM-2416") == "新品"
    assert _judge(bp, "2027-03", "SPU-FM-2416") == "老品"
    assert _judge(bp, "2027-03", "SPU-MC-3026") == "老品"


def test_sku_upload_other_rules_and_readonly(seeded, db, dingtalk):
    bp = login(db, dingtalk, "chensiyu")
    rows = [HEADER, ["MC-3026-GY", "SPU-MC-3026", "镜柜", "2027/13/02"], ["SD-6076-CL", "SPU-SD-6076", "浴室门", "2026-01-01"],
            ["SD-6076-CL", "SPU-SD-6076", "浴室门", "2026-01-01"], ["BT-1701-WH", "SPU-BT-1701", "浴缸", "2026-01-01"],
            ["FM-3022-WH", "SPU-SD-6076", "灯镜", "2026-01-01"], [None, None, "框镜", "2026-01-01"]]
    msgs = [(i["row"], i["message"]) for i in _upload(bp, rows).json()["issues"]]
    assert msgs == [(2, "日期格式错误：2027/13/02，应为 YYYY-MM-DD"), (4, "SKU 重复：与第 3 行相同"),
                    (5, "品类不在清单：浴缸"),
                    (6, "同一 SPU 品类不一致：SPU-SD-6076 在第 3 行为「浴室门」，本行为「灯镜」"),
                    (7, "缺少 SKU、SPU 编码")]
    ceo = login(db, dingtalk, "zhoumingyuan")
    assert ceo.get("/api/master/sku-mapping").json()["can_edit"] is False
    assert _upload(ceo, rows).status_code == 403
