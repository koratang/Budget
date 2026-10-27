"""G1 接口补充：角色分配校验与列表、渠道级范围、主数据读写权限与审计、店铺使用后的币种锁定。"""
from datetime import date

from sqlalchemy import select

from app.models import AuditLog, BudgetVersion, Category, PlatformUnit, Store, UserScope
from app.models.enums import VersionType
from tests.g1.helpers import channel_id, customer_id, dept_id, login, store_id, uid


def test_role_scope_validation_and_listing(seeded, db, dingtalk):
    head = login(db, dingtalk, "linxiao")
    zid = uid(db, "zhaoyiming")
    for body, msg in (({"roles": ["dept_budget"]}, "请选择至少一个部门"),
                      ({"roles": ["operations"]}, "请选择至少一个渠道或店铺"),
                      ({"roles": ["b2b"]}, "请选择至少一个 B端客户")):
        r = head.put(f"/api/admin/users/{zid}/roles", json=body)
        assert r.status_code == 422 and r.json()["message"] == msg
    page = head.get("/api/admin/users", params={"unassigned": True}).json()
    assert [i["name"] for i in page["items"]] == ["赵一鸣"]
    assert page["summary"]["unassigned"] == 1

    # 勾选整个渠道：只存渠道范围，并忽略与所选角色无关的范围
    amazon = channel_id(db, "Amazon")
    r = head.put(f"/api/admin/users/{zid}/roles", json={
        "roles": ["operations", "dept_budget"], "channels": [amazon], "stores": [store_id(db, "Amazon-US-01")],
        "departments": [dept_id(db, "视觉部")], "customers": [customer_id(db, "Bauhaus")]})
    assert r.status_code == 200, r.text
    assert r.json()["scopes"] == {"departments": [dept_id(db, "视觉部")], "channels": [amazon], "stores": [],
                                  "customers": []}
    me = login(db, dingtalk, "zhaoyiming").get("/api/me").json()
    assert len(me["scopes"]["stores"]) == 4

    r = head.put(f"/api/admin/users/{zid}/roles", json={"roles": []})
    assert r.status_code == 200
    assert db.scalar(select(UserScope).where(UserScope.user_id == zid)) is None
    assert db.scalar(select(AuditLog.action).where(AuditLog.object_type == "user_role")
                     .order_by(AuditLog.id.desc()).limit(1)) == "revoke_roles"
    assert login_rejected(db, dingtalk, "zhaoyiming")


def login_rejected(db, dingtalk, userid):
    from tests.conftest import build_client
    c = build_client(db, dingtalk)
    return c.post("/api/dev/login-as", json={"user_id": uid(db, userid)}).json()["message"] == "未开通预算权限，请联系财务负责人"


def test_finance_head_can_be_transferred(seeded, db, dingtalk):
    head = login(db, dingtalk, "linxiao")
    cid = uid(db, "chensiyu")
    assert head.put(f"/api/admin/users/{cid}/roles", json={"roles": ["finance_head"]}).status_code == 200
    assert head.put(f"/api/admin/users/{uid(db, 'linxiao')}/roles", json={"roles": ["finance_bp"]}).status_code == 200


def test_master_permissions_and_used_store_currency(seeded, db, dingtalk):
    for userid in ("wanghao", "jiangfan", "zhengke"):
        c = login(db, dingtalk, userid)
        for path in ("/api/master/stores", "/api/master/sku-mapping", "/api/master/b-customers",
                     "/api/master/departments", "/api/master/account-mapping", "/api/master/fx/budget",
                     "/api/master/fx/actual", "/api/master/budget-accounts"):
            r = c.get(path)
            assert r.status_code == 403 and r.json() == {"code": "forbidden", "message": "无权限"}, path
    ceo = login(db, dingtalk, "zhoumingyuan")
    page = ceo.get("/api/master/stores").json()
    assert page["can_edit"] is False and page["can_mark_new_channel"] is False
    assert ceo.post("/api/master/channels", json={"name": "Temu"}).status_code == 403

    bp = login(db, dingtalk, "chensiyu")
    assert bp.post("/api/master/channels", json={"name": "amazon"}).json()["message"] == "渠道名称已存在"
    s = db.scalar(select(Store).where(Store.name == "Amazon-CA-01"))
    v = BudgetVersion(year=2027, type=VersionType.DRAFT, version_no=1, name="2027 编制稿")
    db.add(v)
    db.flush()
    db.add(PlatformUnit(version_id=v.id, month=date(2027, 1, 1), channel_id=s.channel_id, store_id=s.id,
                        site_id=s.site_id, category_id=db.scalar(select(Category.id).limit(1)), is_new=False))
    db.flush()
    r = bp.put(f"/api/master/stores/{s.id}", json={"channel_id": s.channel_id, "name": s.name, "site_id": s.site_id,
                                                   "currency": "USD", "is_active": True})
    assert r.status_code == 422 and r.json()["message"] == "该店铺已被填报或导入使用，结算币种不可修改"
    assert next(x for x in bp.get("/api/master/stores").json()["stores"] if x["id"] == s.id)["used"] is True

    r = bp.post("/api/master/departments", json={"name": "品牌部"})
    assert r.status_code == 201
    assert bp.post("/api/master/departments", json={"name": "品牌部"}).json()["message"] == "部门名称已存在"
    depts = bp.get("/api/master/departments").json()["items"]
    hr = next(d for d in depts if d["name"] == "人力资源部")
    assert [h["name"] for h in hr["heads"]] == ["吴静"] and [h["name"] for h in hr["budget_staff"]] == ["郑可"]
    audit = db.scalar(select(AuditLog).where(AuditLog.object_type == "department").order_by(AuditLog.id.desc()))
    assert audit.actor_name == "陈思雨" and audit.after == {"name": "品牌部"}
