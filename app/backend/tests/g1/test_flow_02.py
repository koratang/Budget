"""FLOW-02 角色与范围分配（REQ-F01-02，AC-F01-04/05/10；DEC-019）：期望值逐字取自 TDD验收契约 FLOW-02。

渠道×站点偏差报告（API-F10-02）由 G4 实现；本测试以王浩下一次请求加载的数据范围（/api/me 与服务端
ScopeContext 对店铺表的过滤，即报告使用的同一过滤条件）验证「只见 / 出现」的行。
"""
from sqlalchemy import select

from app.core.scope import load_scope
from app.models import AuditLog, BCustomer, Store, UserRole
from app.models.enums import Role
from tests.g1.helpers import login, store_id, uid

ALL_STORES = ["Amazon-CA-01", "Amazon-DE-01", "Amazon-UK-01", "Amazon-US-01", "HomeDepot-US-01", "Lowes-US-01",
              "Lowes-US-02", "Shopify-US-01", "TikTok-US-01", "Wayfair-US-01"]


def visible_stores(db, userid):
    """与报表相同的服务端过滤：每次重新加载角色与范围（不缓存）。"""
    user_id = uid(db, userid)
    roles = db.scalars(select(UserRole.role_code).where(UserRole.user_id == user_id)).all()
    ctx = load_scope(db, user_id, roles)
    return sorted(db.scalars(select(Store.name).where(ctx.store_clause(Store.id, Store.channel_id)))), ctx


def test_assign_scope_takes_effect_on_next_request(seeded, db, dingtalk):
    linxiao = login(db, dingtalk, "linxiao")
    wanghao = login(db, dingtalk, "wanghao")
    wid = uid(db, "wanghao")
    us, ca = store_id(db, "Amazon-US-01"), store_id(db, "Amazon-CA-01")

    r = linxiao.put(f"/api/admin/users/{wid}/roles", json={"roles": ["operations"], "stores": [us]})
    assert r.status_code == 200, r.text
    assert wanghao.get("/api/me").json()["scopes"]["stores"] == [us]
    assert visible_stores(db, "wanghao")[0] == ["Amazon-US-01"]

    r = linxiao.put(f"/api/admin/users/{wid}/roles", json={"roles": ["operations"], "stores": [us, ca]})
    assert r.status_code == 200
    # 无需重新登录：同一会话的下一次请求即按新范围
    assert sorted(wanghao.get("/api/me").json()["scopes"]["stores"]) == sorted([us, ca])
    assert visible_stores(db, "wanghao")[0] == ["Amazon-CA-01", "Amazon-US-01"]
    audits = db.scalars(select(AuditLog).where(AuditLog.object_type == "user_role",
                                               AuditLog.object_id == str(wid))).all()
    assert len(audits) == 2 and audits[-1].actor_name == "林晓"
    assert audits[-1].before["scopes"]["store"] == [us]


def test_non_finance_head_forbidden(seeded, db, dingtalk):
    wid = uid(db, "wanghao")
    for userid in ("chensiyu", "zhaolei"):
        c = login(db, dingtalk, userid)
        assert "roles" not in c.get("/api/me").json()["menus"]
        r = c.get("/api/admin/users")
        assert r.status_code == 403 and r.json() == {"code": "forbidden", "message": "无权限"}
        r = c.put(f"/api/admin/users/{wid}/roles", json={"roles": ["ceo"]})
        assert r.status_code == 403 and r.json()["message"] == "无权限"
    assert db.scalars(select(UserRole.role_code).where(UserRole.user_id == wid)).all() == ["operations"]


def test_cannot_revoke_last_finance_head(seeded, db, dingtalk):
    linxiao = login(db, dingtalk, "linxiao")
    lid = uid(db, "linxiao")
    r = linxiao.put(f"/api/admin/users/{lid}/roles", json={"roles": []})
    assert r.status_code == 409
    assert r.json()["message"] == "系统至少需要保留一名财务负责人"
    r = linxiao.put(f"/api/admin/users/{lid}/roles", json={"roles": ["finance_bp"]})
    assert r.status_code == 409 and r.json()["code"] == "last_finance_head"
    assert db.scalars(select(UserRole.role_code).where(UserRole.user_id == lid)).all() == [Role.FINANCE_HEAD]
    assert db.scalar(select(AuditLog).where(AuditLog.object_type == "user_role")) is None


def test_management_sees_all_stores_and_customers(seeded, db, dingtalk):
    all_customers = sorted(db.scalars(select(BCustomer.name)))
    for userid in ("zhoumingyuan", "linxiao", "chensiyu"):
        me = login(db, dingtalk, userid).get("/api/me").json()
        assert me["all_company"] is True
        stores, ctx = visible_stores(db, userid)
        assert stores == ALL_STORES
        assert sorted(db.scalars(select(BCustomer.name).where(ctx.customer_clause(BCustomer.id)))) == all_customers
