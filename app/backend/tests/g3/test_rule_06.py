"""RULE-06 版本锁定（DEC-016、DEC-020）：年初原始目标、调整后目标 V3、Q2 快照的修改全部被拒。
期望值逐字取自 TDD验收契约.md RULE-06 行。

接口层：本组服务（ensure_version_editable、发布、调整提交）拒绝修改锁定版本；填报表格的单元格保存接口
（G2 PATCH /filling-units/{id}/cells）应在写入前调用 ensure_version_editable / open_months。
"""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict
from app.models import PlatformUnit
from app.models.enums import VersionType
from app.services import versions as svc


def _db_rejects(db, sql, params, message):
    with pytest.raises(DBAPIError) as e:
        with db.begin_nested():
            db.execute(text(sql), params)
    assert message in str(e.value)


def test_rule_06_locked_versions(g3):
    db = g3.db
    g3.set_now("2027-05-12 10:00")
    stores = {"Amazon-US-01": {m: (600000, 150000) for m in range(1, 13)}}
    v1 = g3.make_version(stores=stores)
    v3 = g3.make_version(vtype=VersionType.ADJUSTED_TARGET, version_no=3, quarter=2, stores=stores,
                         approved_at="2027-05-12 10:00")
    q2 = g3.make_version(vtype=VersionType.SNAPSHOT, version_no=2, quarter=2, stores=stores,
                         approved_at="2027-05-12 10:00")
    before = [(u.id, u.revenue_cny) for u in db.scalars(select(PlatformUnit).order_by(PlatformUnit.id))]

    for v in (v1, v3, q2):
        with pytest.raises(Conflict) as e:
            svc.ensure_version_editable(db, v.id)
        assert e.value.message == "版本已锁定，不能修改"
        assert svc.open_months(db, v.id) == set()
        _db_rejects(db, "UPDATE platform_unit SET revenue_cny = 1 WHERE version_id = :v", {"v": v.id},
                    "版本已锁定，不能修改")
        _db_rejects(db, "DELETE FROM platform_unit WHERE version_id = :v", {"v": v.id}, "版本已锁定，不能修改")
        _db_rejects(db, "UPDATE budget_version SET name = 'x' WHERE id = :v", {"v": v.id}, "版本已锁定，不能修改")
    # 快照再次发布被拒
    r = g3.client("林晓").post(f"/api/versions/rolling/{q2.id}/publish", json={})
    assert r.status_code == 409
    # 已锁定年度的预算汇率不能直接 UPDATE / DELETE
    _db_rejects(db, "UPDATE fx_budget SET rate = 7.5 WHERE year = 2027 AND currency = 'USD'", {},
                "已随年初原始目标锁定")
    _db_rejects(db, "DELETE FROM fx_budget WHERE year = 2027 AND currency = 'USD'", {}, "已随年初原始目标锁定")
    assert [(u.id, u.revenue_cny) for u in db.scalars(select(PlatformUnit).order_by(PlatformUnit.id))] == before

    # 锁定版本只能通过新版本演进：发起调整复制出未锁定的调整稿
    g3.make_version(vtype=VersionType.ADJUSTED_TARGET, version_no=2, quarter=1, stores=stores)
    r = g3.client("林晓").post("/api/versions/adjustments")
    # 本季度（Q2）已有 V3 但不是经调整记录生效的；发起成功并生成调整稿
    assert r.status_code == 200, r.text
    draft = svc.get_version(db, r.json()["draft_version_id"])
    assert not draft.locked and draft.source_version_id == v3.id
    assert svc.ensure_version_editable(db, draft.id).id == draft.id
