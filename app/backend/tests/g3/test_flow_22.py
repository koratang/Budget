"""FLOW-22 金蝶月度导入：整份拒绝、未归属渠道、覆盖确认与保留、24 个月历史导入（AC-F09-01~04、NFR-004）。

期望值逐字取自 TDD验收契约.md FLOW-22 行。
"""
from decimal import Decimal

from sqlalchemy import func, select

from app.models import AuditLog, ImportBatch, KingdeeActual
from app.models.enums import ImportStatus
from tests.g3.fixtures_g3 import fixture_path


def _business_counts(db):
    return {t.__tablename__: db.scalar(select(func.count()).select_from(t)) for t in (KingdeeActual,)}


def test_flow_22_kingdee_import(g3):
    db = g3.db
    # 前置：2027-04 已有导入「金蝶_2027-04_利润表.xlsx」（陈思雨，2027-05-10 16:42）
    g3.set_now("2027-05-10 16:42")
    first = g3.import_file(fixture_path("金蝶_2027-04_利润表.xlsx"), "kingdee")
    assert first["status"] == "imported"
    g3.set_now("2027-05-12 10:00")
    before = _business_counts(db)

    # 1. 含 4 个问题行的文件：整份不写入，逐行列出行号、问题类型、涉及编码或名称
    bad = g3.upload(fixture_path("金蝶_2027-04_利润表_v2.xlsx"), "kingdee")
    assert bad["status"] == "failed"
    issues = {i["row"]: i for i in bad["issues"]}
    assert sorted(issues) == [7, 15, 22, 31]
    assert (issues[7]["type"], issues[7]["name"]) == ("期间格式错误", "2027/4")
    assert (issues[15]["type"], issues[15]["name"]) == ("部门不在主数据中", "视觉二部")
    assert (issues[22]["type"], issues[22]["name"]) == ("店铺不在主数据中", "Amazon-MX-01")
    assert issues[31]["type"] == "金蝶科目未映射" and issues[31]["name"].startswith("6601.99")
    assert _business_counts(db) == before
    assert db.scalar(select(func.count()).select_from(ImportBatch).where(
        ImportBatch.parent_batch_id == bad["id"])) == 0

    # 2. 修正后上传：校验通过，提示覆盖（原文件名、导入人、时间），未确认覆盖时 409 且不写入
    fixed = g3.upload(fixture_path("金蝶_2027-04_利润表_v3.xlsx"), "kingdee")
    assert fixed["status"] == "passed"
    assert fixed["needs_overwrite"] is True
    assert fixed["overwrite"] == [{"periods": ["2027-04"], "file_name": "金蝶_2027-04_利润表.xlsx",
                                   "imported_by": "陈思雨", "imported_at": "2027-05-10 16:42"}]
    unassigned = fixed["summary"]["unassigned"]
    assert [(u["code"], u["amount_display"]) for u in unassigned] == [("6601.06", "¥ 12,000.00")]
    r = g3.confirm(fixed["id"], overwrite=False)
    assert r.status_code == 409 and r.json()["code"] == "needs_overwrite"
    assert _business_counts(db) == before

    # 3. 确认覆盖：新批次生效，原批次「已被替换」且导入记录保留文件名、导入人、导入时间
    r = g3.confirm(fixed["id"], overwrite=True)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "imported"
    old = db.get(ImportBatch, first["id"])
    assert old.status == ImportStatus.REPLACED
    records = g3.client("陈思雨").get("/api/imports").json()["records"]
    old_rec = next(x for x in records if x["id"] == first["id"])
    assert (old_rec["file_name"], old_rec["imported_by"], old_rec["imported_at"], old_rec["status_label"]) == \
        ("金蝶_2027-04_利润表.xlsx", "陈思雨", "2027-05-10 16:42", "已被替换")
    new_rec = next(x for x in records if x["id"] == fixed["id"])
    assert new_rec["status_label"] == "生效"
    # 旧批次的行仍在库
    old_child = db.scalar(select(ImportBatch).where(ImportBatch.parent_batch_id == first["id"]))
    assert db.scalar(select(func.count()).select_from(KingdeeActual).where(KingdeeActual.batch_id == old_child.id)) == 34

    # 4. 仓储杂费 12,000.00 无平台/店铺核算且非部门费用科目 → 2027-04「未归属渠道」
    new_child = db.scalar(select(ImportBatch).where(ImportBatch.parent_batch_id == fixed["id"]))
    row = db.scalar(select(KingdeeActual).where(KingdeeActual.batch_id == new_child.id,
                                                KingdeeActual.summary == "仓储杂费"))
    assert row.unassigned is True and row.amount == Decimal("12000") and row.store_id is None
    assert row.month.isoformat() == "2027-04-01"

    # 5. 历史文件 2025-01 至 2026-12 共 24 个期间逐月入库，历史网格 24 格均为已入库
    hist = g3.import_file(fixture_path("金蝶_历史_2025-01至2026-12.xlsx"), "kingdee-history")
    assert len(hist["periods"]) == 24 and hist["periods"][0] == "2025-01" and hist["periods"][-1] == "2026-12"
    children = db.scalars(select(ImportBatch).where(ImportBatch.parent_batch_id == hist["id"])).all()
    assert len(children) == 24 and all(c.status == ImportStatus.EFFECTIVE for c in children)
    overview = g3.client("陈思雨").get("/api/imports").json()
    assert len(overview["history_grid"]) == 24
    assert all(g["imported"] for g in overview["history_grid"])

    # NFR-004：上传、确认、覆盖均有审计
    actions = set(db.scalars(select(AuditLog.action).where(AuditLog.object_type == "import_batch")))
    assert {"import_uploaded", "import_confirmed"} <= actions
    overwrite_audit = db.scalar(select(AuditLog).where(AuditLog.action == "import_confirmed",
                                                       AuditLog.object_id == str(fixed["id"])))
    assert overwrite_audit.after["overwrite"] is True and overwrite_audit.actor_name == "陈思雨"


def test_flow_22_only_finance_bp_uploads(g3):
    r = g3.client("王浩").get("/api/imports")
    assert r.status_code == 403 and r.json() == {"code": "forbidden", "message": "无权限"}
    path = fixture_path("金蝶_2027-04_利润表_v3.xlsx")
    r = g3.client("林晓").post("/api/imports", files={"file": (path.name, path.read_bytes())},
                             data={"source": "kingdee"})
    assert r.status_code == 403
