"""数据范围与权限：AC-F01-06~11、NFR-003、菜单矩阵。"""
import pytest
from sqlalchemy import select

from app.core.auth import CurrentUser
from app.core.errors import Forbidden
from app.core.menus import menus_for
from app.core.scope import ensure_writable_fields, load_scope, require_roles, restrict_fields
from app.models import BCustomer, Channel, Department, Store, User, UserRole, UserScope
from app.models.enums import Role


def scope_of(db, userid):
    user = db.scalar(select(User).where(User.dingtalk_userid == userid))
    roles = db.scalars(select(UserRole.role_code).where(UserRole.user_id == user.id)).all()
    return load_scope(db, user.id, roles)


def names(db, model, clause):
    return sorted(db.scalars(select(model.name).where(clause)))


def test_operations_only_sees_assigned_store(seeded):
    db = seeded
    ctx = scope_of(db, "wanghao")
    assert names(db, Store, ctx.store_clause(Store.id, Store.channel_id)) == ["Amazon-US-01"]
    us = db.scalar(select(Store).where(Store.name == "Amazon-US-01"))
    ca = db.scalar(select(Store).where(Store.name == "Amazon-CA-01"))
    ctx.ensure_store(us.id, us.channel_id)
    with pytest.raises(Forbidden):
        ctx.ensure_store(ca.id, ca.channel_id)


def test_scope_change_takes_effect_on_next_load(seeded):
    """AC-F01-04：范围改为 US + CA 后，下一次加载即包含 CA（范围不缓存）。"""
    db = seeded
    ca = db.scalar(select(Store).where(Store.name == "Amazon-CA-01"))
    uid = db.scalar(select(User.id).where(User.dingtalk_userid == "wanghao"))
    db.add(UserScope(user_id=uid, scope_type="store", object_id=ca.id))
    db.flush()
    ctx = scope_of(db, "wanghao")
    assert names(db, Store, ctx.store_clause(Store.id)) == ["Amazon-CA-01", "Amazon-US-01"]


def test_channel_scope_expands_to_stores(seeded):
    db = seeded
    uid = db.scalar(select(User.id).where(User.dingtalk_userid == "zhaoyiming"))
    amazon = db.scalar(select(Channel.id).where(Channel.name == "Amazon"))
    db.add_all([UserRole(user_id=uid, role_code=Role.OPERATIONS),
                UserScope(user_id=uid, scope_type="channel", object_id=amazon)])
    db.flush()
    ctx = scope_of(db, "zhaoyiming")
    assert names(db, Store, ctx.store_clause(Store.id, Store.channel_id)) == [
        "Amazon-CA-01", "Amazon-DE-01", "Amazon-UK-01", "Amazon-US-01"]


def test_department_roles_only_see_own_department(seeded):
    db = seeded
    for userid in ("wujing", "zhengke"):
        ctx = scope_of(db, userid)
        assert names(db, Department, ctx.department_clause(Department.id)) == ["人力资源部"]
    hr = db.scalar(select(Department.id).where(Department.name == "人力资源部"))
    fin = db.scalar(select(Department.id).where(Department.name == "财务部"))
    ctx.ensure_department(hr)
    with pytest.raises(Forbidden):
        ctx.ensure_department(fin)


def test_b2b_only_sees_assigned_customers(seeded):
    db = seeded
    ctx = scope_of(db, "sunting")
    assert names(db, BCustomer, ctx.customer_clause(BCustomer.id)) == ["Ferguson", "Menards"]
    bauhaus = db.scalar(select(BCustomer.id).where(BCustomer.name == "Bauhaus"))
    with pytest.raises(Forbidden):
        ctx.ensure_customer(bauhaus)


@pytest.mark.parametrize("userid", ["zhoumingyuan", "linxiao", "chensiyu"])
def test_management_sees_whole_company(seeded, userid):
    db = seeded
    ctx = scope_of(db, userid)
    assert ctx.all_company
    assert len(names(db, Store, ctx.store_clause(Store.id))) == 10
    assert len(names(db, BCustomer, ctx.customer_clause(BCustomer.id))) == 3
    assert len(names(db, Department, ctx.department_clause(Department.id))) == 15


def test_user_without_scope_sees_nothing(seeded):
    ctx = scope_of(seeded, "jiangfan")  # 物流物控：无行范围
    assert names(seeded, Store, ctx.store_clause(Store.id)) == []


def test_logistics_field_level_view(seeded):
    """AC-F01-09：物流物控视图只含维度列与四项物流比例；写其他字段 403。"""
    ctx = scope_of(seeded, "jiangfan")
    row = {"month": "2027-03", "channel_name": "Amazon", "site_name": "美国", "category_name": "浴室柜",
           "first_leg_rate": "6", "last_mile_rate": "8", "storage_rate": "2", "tariff_rate": "4",
           "purchase_cost_rate": "30", "revenue_cny": "615168", "sales_qty": "1200", "gross_profit": "98426.88"}
    view = restrict_fields(ctx, row)
    assert set(view) == {"month", "channel_name", "site_name", "category_name", "first_leg_rate", "last_mile_rate",
                         "storage_rate", "tariff_rate"}
    ensure_writable_fields(ctx, ["first_leg_rate", "tariff_rate"])
    with pytest.raises(Forbidden):
        ensure_writable_fields(ctx, ["purchase_cost_rate"])
    assert restrict_fields(scope_of(seeded, "chensiyu"), row) == row


def test_require_roles_dependency(seeded):
    db = seeded
    user = db.scalar(select(User).where(User.dingtalk_userid == "zhaolei"))
    dep = require_roles(Role.FINANCE_HEAD)
    with pytest.raises(Forbidden) as e:
        dep(CurrentUser(user=user, roles=frozenset({Role.DEPT_HEAD}), auth_source="dev", session_id=0))
    assert e.value.body() == {"code": "forbidden", "message": "无权限"}
    assert dep.required_roles == {Role.FINANCE_HEAD}


def test_menu_matrix():
    assert "roles" in menus_for({Role.FINANCE_HEAD})
    for role in set(Role.ALL) - {Role.FINANCE_HEAD}:
        assert "roles" not in menus_for({role})
    ops = menus_for({Role.OPERATIONS})
    assert not {"stores", "tasks", "import", "rules", "report-company"} & set(ops)
    assert {"workbench", "my-filling", "report-channel", "alerts"} <= set(ops)
    assert {"stores", "import", "rules", "report-company"} <= set(menus_for({Role.FINANCE_BP}))
    # 一人多角色取并集
    assert set(menus_for({Role.DEPT_HEAD, Role.LOGISTICS})) == set(menus_for({Role.DEPT_HEAD})) | set(
        menus_for({Role.LOGISTICS}))


def test_me_returns_menus_and_scopes(seeded, client):
    client.post("/api/auth/dingtalk/h5", json={"auth_code": "h5-sunting"})
    me = client.get("/api/me").json()
    db = seeded
    ids = sorted(db.scalars(select(BCustomer.id).where(BCustomer.name.in_(["Ferguson", "Menards"]))))
    assert me["scopes"]["customers"] == ids
    assert "report-channel" in me["menus"] and "report-category" not in me["menus"]
