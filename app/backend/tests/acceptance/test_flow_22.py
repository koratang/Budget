"""FLOW-22 金蝶月度导入（REQ-F09-01、AC-F09-01~04、NFR-004）：整份拒绝、覆盖确认与保留、未归属渠道、24 个月历史。

真实路由 + 权限 + 数据库；期望值逐字取自 TDD验收契约.md FLOW-22。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models import AuditLog, ImportBatch, KingdeeActual
from app.models.enums import ImportStatus
from app.services.dept_expense import dept_actuals, imported_months
from tests.acceptance.e3_scenarios import flow21
from tests.g3.conftest import g3  # noqa: F401
from tests.g3.fixtures_g3 import fixture_path


def _kd_rows(db):
    return db.scalar(select(func.count()).select_from(KingdeeActual))


def test_flow_22(g3):  # noqa: F811
    db = g3.db
    g3.set_now("2027-01-05 09:00")
    flow21(g3)                       # 2027 年度预算（渠道×站点偏差报告的对比基准）
    # 前置：2027-04 已有导入「金蝶_2027-04_利润表.xlsx」（陈思雨，2027-05-10 16:42）
    g3.set_now("2027-05-10 16:42")
    first = g3.import_file(fixture_path("金蝶_2027-04_利润表.xlsx"), "kingdee")
    g3.set_now("2027-05-12 10:00")
    before = _kd_rows(db)

    # 首次上传「金蝶_2027-04_利润表_v2.xlsx」：校验未通过，列出 4 行（行号、问题类型、涉及编码或名称）
    bad = g3.upload(fixture_path("金蝶_2027-04_利润表_v2.xlsx"), "kingdee")
    assert bad["status"] == "failed"
    issues = {i["row"]: i for i in bad["issues"]}
    assert sorted(issues) == [7, 15, 22, 31]
    assert (issues[7]["type"], issues[7]["name"]) == ("期间格式错误", "2027/4")
    assert (issues[15]["type"], issues[15]["name"]) == ("部门不在主数据中", "视觉二部")
    assert (issues[22]["type"], issues[22]["name"]) == ("店铺不在主数据中", "Amazon-MX-01")
    assert issues[31]["type"] == "金蝶科目未映射" and "6601.99" in issues[31]["name"]
    assert _kd_rows(db) == before                                   # 业务表行数不变

    # 修正后上传：覆盖前提示原文件名、导入人、时间
    fixed = g3.upload(fixture_path("金蝶_2027-04_利润表_v3.xlsx"), "kingdee")
    assert fixed["status"] == "passed" and fixed["needs_overwrite"] is True
    assert fixed["overwrite"] == [{"periods": ["2027-04"], "file_name": "金蝶_2027-04_利润表.xlsx",
                                   "imported_by": "陈思雨", "imported_at": "2027-05-10 16:42"}]
    r = g3.confirm(fixed["id"], overwrite=False)
    assert r.status_code == 409 and _kd_rows(db) == before
    r = g3.confirm(fixed["id"], overwrite=True)                    # 确认覆盖
    assert r.status_code == 200 and r.json()["status"] == "imported"
    assert db.get(ImportBatch, first["id"]).status == ImportStatus.REPLACED
    records = g3.client("陈思雨").get("/api/imports").json()["records"]
    old = next(x for x in records if x["id"] == first["id"])
    assert (old["status_label"], old["file_name"], old["imported_by"], old["imported_at"]) == \
        ("已被替换", "金蝶_2027-04_利润表.xlsx", "陈思雨", "2027-05-10 16:42")
    assert next(x for x in records if x["id"] == fixed["id"])["status_label"] == "生效"

    # 「仓储杂费 12,000.00」计入 2027-04「未归属渠道」，并在渠道×站点偏差单列
    child = db.scalar(select(ImportBatch).where(ImportBatch.parent_batch_id == fixed["id"]))
    row = db.scalar(select(KingdeeActual).where(KingdeeActual.batch_id == child.id,
                                                KingdeeActual.summary == "仓储杂费"))
    assert (row.unassigned, row.amount, row.month) == (True, Decimal("12000"), date(2027, 4, 1))
    rep = g3.client("林晓").get("/api/reports/channel-site", params={"month": "2027-04"})
    assert rep.status_code == 200, rep.text
    un = rep.json()["unassigned"]
    assert un["name"] == "未归属渠道"
    assert [(x["label"], Decimal(x["actual"])) for x in un["lines"]] == [("仓储费", Decimal("12000"))]

    # 历史文件 2025-01 至 2026-12 共 24 个期间逐月入库，历史网格 24 格均为已入库
    hist = g3.import_file(fixture_path("金蝶_历史_2025-01至2026-12.xlsx"), "kingdee-history")
    assert len(hist["periods"]) == 24
    children = db.scalars(select(ImportBatch).where(ImportBatch.parent_batch_id == hist["id"])).all()
    assert len(children) == 24 and all(c.status == ImportStatus.EFFECTIVE for c in children)
    grid = g3.client("陈思雨").get("/api/imports").json()["history_grid"]
    assert len(grid) == 24 and all(g["imported"] for g in grid)
    # 用于 FLOW-16 历史参考：部门费用历史实际按月可取（人力资源部 2026-04 工资 = 90,000 + 4 × 500）
    hr = dept_actuals(db, g3.dept("人力资源部").id)
    assert date(2026, 4, 1) in imported_months(db)
    assert hr[g3.account("工资薪酬").id][date(2026, 4, 1)] == Decimal("92000")
    # 用于 FLOW-27 同比：2027-01～04 的上年同期（2026-01～04）已导入，增速可计算
    g3.fake_kingdee_months(["2027-01", "2027-02", "2027-03"])
    comp = g3.client("林晓").get("/api/reports/company", params={"year": 2027}).json()
    assert comp["growth"]["available"] is True
    # 2026-01～04 Amazon-US-01 收入 465,000 + 470,000 + 475,000 + 480,000（历史文件逐月入库值）
    assert Decimal(comp["growth"]["revenue"]["prior"]) == Decimal("1890000")

    # NFR-004：上传、确认（含覆盖）进入审计
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.object_type == "import_batch")))
    assert {"import_uploaded", "import_confirmed"} <= actions
