"""业财分析工作区（API-F15-01~03）：权限、乐观锁、示例标记、审计、恢复示例数据。"""
from sqlalchemy import select

from app.core.menus import menus_for
from app.models import AuditLog
from app.models.enums import Role

from tests.g4 import builders as B

POLICY = [{"id": "p1", "date": "2027-03-05", "seg": "关税", "title": "美国对浴室柜加征 10% 关税",
           "impact": "毛利率下降约 1.2 个百分点", "level": "高"}]


def test_permissions_and_menus(client, seeded):
    db = seeded
    for role in (Role.CEO, Role.FINANCE_HEAD, Role.FINANCE_BP):
        assert "bizfin-finance" in menus_for({role}) and "bizfin-data" in menus_for({role})
    for role in (Role.OPERATIONS, Role.B2B, Role.LOGISTICS, Role.DEPT_HEAD, Role.DEPT_BUDGET):
        assert not [m for m in menus_for({role}) if m.startswith("bizfin-")]

    B.login(client, db, "wanghao")  # 运营：不可见
    assert client.get("/api/bizfin/sections").status_code == 403
    B.login(client, db, "zhoumingyuan")  # CEO：只读
    r = client.get("/api/bizfin/sections").json()
    assert r == {"sections": {}, "can_edit": False, "can_reset": False}
    assert client.put("/api/bizfin/sections/policy", json={"data": POLICY, "revision": None,
                                                         "is_demo": True}).status_code == 403
    B.login(client, db, "chensiyu")  # 财务BP：可编辑、不可恢复示例数据
    r = client.get("/api/bizfin/sections").json()
    assert (r["can_edit"], r["can_reset"]) == (True, False)
    assert client.post("/api/bizfin/reset").status_code == 403


def test_save_revision_conflict_and_audit(client, seeded):
    db = seeded
    B.login(client, db, "chensiyu")
    r = client.put("/api/bizfin/sections/policy", json={"data": POLICY, "revision": None, "is_demo": True})
    assert r.status_code == 200 and r.json()["revision"] == 1 and r.json()["updated_by"] == "陈思雨"

    # 基于旧版本再存：409，提示谁改过
    stale = client.put("/api/bizfin/sections/policy", json={"data": [], "revision": None, "is_demo": True})
    assert stale.status_code == 409 and "陈思雨" in stale.json()["message"]
    assert stale.json()["details"]["revision"] == 1

    r = client.put("/api/bizfin/sections/policy", json={"data": POLICY + POLICY, "revision": 1, "is_demo": False})
    assert r.json()["revision"] == 2 and r.json()["is_demo"] is False
    got = client.get("/api/bizfin/sections").json()["sections"]
    assert list(got) == ["policy"] and len(got["policy"]["data"]) == 2

    assert client.put("/api/bizfin/sections/salary", json={"data": [], "revision": None,
                                                         "is_demo": True}).status_code == 404
    assert client.put("/api/bizfin/sections/keywork", json={"data": "文本", "revision": None,
                                                          "is_demo": True}).status_code == 422
    # 经营建议模块已删除（revision 7）：不再接受该部分
    assert client.put("/api/bizfin/sections/advice", json={"data": [], "revision": None,
                                                         "is_demo": True}).status_code == 404
    logs = db.scalars(select(AuditLog).where(AuditLog.action == "bizfin.save")).all()
    assert [(a.object_id, a.after["revision"]) for a in logs] == [("policy", 1), ("policy", 2)]


def test_reset_by_finance_head(client, seeded):
    db = seeded
    B.login(client, db, "linxiao")
    client.put("/api/bizfin/sections/keywork", json={"data": [{"id": "k1", "title": "Wayfair 新仓上线"}],
                                                    "revision": None, "is_demo": False})
    assert client.post("/api/bizfin/reset").json() == {"ok": True}
    assert client.get("/api/bizfin/sections").json()["sections"] == {}
    log = db.scalar(select(AuditLog).where(AuditLog.action == "bizfin.reset"))
    assert log.before == {"keys": ["keywork"]} and log.actor_name == "林晓"
