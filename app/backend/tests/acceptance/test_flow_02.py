"""FLOW-02 验收（API 层，真实路由 + 数据库）：期望值逐字取自 TDD验收契约 FLOW-02。

林晓为王浩保存「运营 · 渠道/店铺范围 = Amazon-US-01」，王浩刷新偏差报告 → 只见 Amazon-US-01 行；改为 Amazon-US-01、
Amazon-CA-01 后王浩下一次请求即出现 Amazon-CA-01 行（无需重新登录）；陈思雨、赵磊打开角色分配与调用保存接口 → 403
「无权限」且菜单无「角色与权限」；林晓撤销自己唯一的财务负责人角色 → 「系统至少需要保留一名财务负责人」且不写入；
周明远、林晓、陈思雨打开渠道×站点偏差 → 全部店铺、B 端客户与未归属渠道行。
"""
from sqlalchemy import select

from app.models import BCustomer, Store, UserRole
from app.models.enums import Role
from tests.acceptance.e1_helpers import People, report_world, uid

REPORT = "/api/reports/channel-site"


def _names(c):
    r = c.get(REPORT, params={"month": "2027-04"})
    assert r.status_code == 200, r.text
    d = r.json()
    return [x["name"] for x in d["rows"]], [x["name"] for x in d["b2b_rows"]], d["unassigned"]


def test_flow_02(seeded, dingtalk, tmp_path):
    db = seeded
    p = People(db, dingtalk, tmp_path)
    report_world(db, p)
    lin, wang = p("linxiao"), p("wanghao")
    wid = uid(db, "wanghao")
    us = db.scalar(select(Store.id).where(Store.name == "Amazon-US-01"))
    ca = db.scalar(select(Store.id).where(Store.name == "Amazon-CA-01"))

    r = lin.put(f"/api/admin/users/{wid}/roles", json={"roles": ["operations"], "stores": [us]})
    assert r.status_code == 200, r.text
    rows, b2b, unassigned = _names(wang)
    assert rows == ["Amazon-US-01"] and b2b == [] and unassigned is None

    r = lin.put(f"/api/admin/users/{wid}/roles", json={"roles": ["operations"], "stores": [us, ca]})
    assert r.status_code == 200, r.text
    rows, _, _ = _names(wang)  # 同一会话（未重新登录）的下一次请求
    assert sorted(rows) == ["Amazon-CA-01", "Amazon-US-01"]

    for who in ("chensiyu", "zhaolei"):
        c = p(who)
        assert "roles" not in c.get("/api/me").json()["menus"]
        r = c.get("/api/admin/users")
        assert r.status_code == 403 and r.json() == {"code": "forbidden", "message": "无权限"}
        r = c.put(f"/api/admin/users/{wid}/roles", json={"roles": ["ceo"]})
        assert r.status_code == 403 and r.json()["message"] == "无权限"
    assert db.scalars(select(UserRole.role_code).where(UserRole.user_id == wid)).all() == ["operations"]

    lid = uid(db, "linxiao")
    r = lin.put(f"/api/admin/users/{lid}/roles", json={"roles": []})
    assert r.status_code == 409 and r.json()["message"] == "系统至少需要保留一名财务负责人"
    assert db.scalars(select(UserRole.role_code).where(UserRole.user_id == lid)).all() == [Role.FINANCE_HEAD]

    all_stores = sorted(db.scalars(select(Store.name)))
    all_customers = sorted(db.scalars(select(BCustomer.name)))
    for who in ("zhoumingyuan", "linxiao", "chensiyu"):
        rows, b2b, unassigned = _names(p(who))
        assert sorted(rows) == all_stores, who
        assert sorted(b2b) == all_customers, who
        assert unassigned is not None and unassigned["name"] == "未归属渠道", who
