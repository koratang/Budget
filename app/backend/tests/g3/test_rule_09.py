"""RULE-09 导入校验性能（NFR-002）：5 万行金蝶与 BI 文件（合法版与末行出错版）各上传一次，
import_batch 的 uploaded_at → validated_at ≤ 60 秒；出错版仍列出全部错误。实测秒数打印并写入
tests/g3/rule09_timing.log（运行 pytest -s 可直接看到）。期望值逐字取自 TDD验收契约.md RULE-09 行。

「校验期间其他页面请求正常响应」：校验在线程池中执行，在真实运行的服务上另行验证（见 G3 汇报）。
"""
import time
from pathlib import Path

from app.models import ImportBatch
from tests.g3.fixtures_g3 import BI_HEADER, KINGDEE_HEADER, bi, kd, write_xlsx

N = 50_000
LOG = Path(__file__).with_name("rule09_timing.log")


def kingdee_rows(bad: bool):
    stores = [("Amazon-US-01", "美国"), ("Wayfair-US-01", "美国"), ("Amazon-UK-01", "英国"), ("Amazon-DE-01", "德国")]
    accts = ["收入", "采购", "佣金", "推广", "头程", "尾程"]
    rows = []
    for i in range(N):
        if i % 10 == 9:
            rows.append(kd("2027-04", "工资", 1000 + i % 500, dept="人力资源部"))
        else:
            s, site = stores[i % 4]
            rows.append(kd("2027-04", accts[i % 6], 100 + (i % 997) * 3, store=s, site=site))
    if bad:
        rows[-1] = kd("2027/4", "工资", 1000, dept="人力资源部")
    return rows


def bi_rows(bad: bool):
    skus = ["FM-2416-WH", "LM-3020-BK", "MC-1810-OK", "SD-6070-CL", "BT-1708-WH", "BT-1708-GY"]
    rows = [bi("2027-04" if i % 2 else "2027-03", "Amazon-US-01" if i % 3 else "Wayfair-US-01", "美国",
               skus[i % 6], 1 + i % 7, 150 + i % 300, "USD", 10, 20) for i in range(N)]
    if bad:
        rows[-1] = bi("2027-04", "Amazon-US-01", "美国", "ZZ-9999-NO", 1, 100, "USD")
    return rows


def test_rule_09_validation_within_60s(g3):
    g3.add_skus()
    results = []
    cases = [("金蝶_5万行_合法.xlsx", "kingdee", KINGDEE_HEADER, kingdee_rows(False), 0),
             ("金蝶_5万行_末行出错.xlsx", "kingdee", KINGDEE_HEADER, kingdee_rows(True), 1),
             ("BI_5万行_合法.xlsx", "bi", BI_HEADER, bi_rows(False), 0),
             ("BI_5万行_末行出错.xlsx", "bi", BI_HEADER, bi_rows(True), 1)]
    for name, source, header, rows, expected_errors in cases:
        path = write_xlsx(g3.tmp / name, header, rows)
        t0 = time.perf_counter()
        batch = g3.upload(path, source)
        wall = time.perf_counter() - t0
        b = g3.db.get(ImportBatch, batch["id"])
        seconds = (b.validated_at - b.uploaded_at).total_seconds()
        results.append(f"{name}: uploaded_at→validated_at {seconds:.2f} 秒（含上传请求 {wall:.2f} 秒），"
                       f"状态 {batch['status']}，问题 {len(batch['issues'])} 个")
        assert seconds <= 60 and wall <= 60
        if expected_errors:
            assert batch["status"] == "failed" and len(batch["issues"]) == 1
            assert batch["issues"][0]["row"] in (N + 1, f"第 {N + 1:,} 行起 · 共 1 行")
        else:
            assert batch["status"] == "passed" and batch["row_count"] == N
    LOG.write_text("\n".join(results) + "\n", encoding="utf-8")
    print("\n" + "\n".join(results))
