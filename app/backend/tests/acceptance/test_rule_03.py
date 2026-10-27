"""RULE-03 审计（NFR-004、REQ-F01-02、REQ-F07-02、REQ-F08-01、REQ-F09-01、REQ-F12-02；DEC-010）。
期望值逐字取自 TDD验收契约.md RULE-03 行：

五类操作各产生审计行，含操作人、时间（带时区）、操作类型、对象、修改前值与修改后值，且与业务修改同事务（业务回滚时
无审计行）；UPDATE 与 DELETE 均报错且审计行数不变；不存在删除或修改审计的 HTTP 接口，无自动清理任务。
"""
from __future__ import annotations

import inspect
import os
import re
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from app.dingtalk import scheduler as scheduler_mod
from app.main import create_app
from app.models import AuditLog, BudgetVersion, FillingUnit, ImportBatch, Rule, RuleVersion, Store, User, UserScope
from app.models.enums import VersionType
from tests.acceptance.e4_common import iter_api_routes
from tests.conftest import TEST_DATABASE_URL, make_settings
from tests.g2.helpers import login, minimal_units, publish, save, submit, unit_by_name
from tests.g2.test_smoke_03 import _cells
from tests.g3.conftest import G3
from tests.g3.fixtures_g3 import fixture_path

# 使用 E4 专用应用库 budget_acc4（真实提交 / 子进程重建库）：只在 E4 环境显式运行，避免其他执行者的全量 pytest 改动该库
E4_LIVE = pytest.mark.skipif(os.environ.get("E4_LIVE") != "1", reason="E4 专用：设置 E4_LIVE=1 运行")
BACKEND = Path(__file__).resolve().parents[2]


def _new_audits(db, since_id: int) -> list[AuditLog]:
    """该操作之后的审计行（登录审计为排查用途，非五类操作，排除在外）。"""
    return db.scalars(select(AuditLog).where(AuditLog.id > since_id, AuditLog.action != "login")
                      .order_by(AuditLog.id)).all()


def _max_id(db) -> int:
    return db.scalar(select(func.coalesce(func.max(AuditLog.id), 0)))


def _assert_complete(rows: list[AuditLog], *, actor: str, actions: set[str], label: str) -> None:
    """该类操作产生的审计行：操作人、带时区时间、操作类型、对象、修改前 / 修改后值齐全。"""
    got = {r.action for r in rows}
    assert actions <= got, f"{label}：缺少审计 {actions - got}（实有 {got}）"
    for r in rows:
        if r.action not in actions:
            continue
        assert r.actor_name and (r.actor_userid or r.actor_name == "system-bootstrap"), label
        assert r.occurred_at.tzinfo is not None and r.occurred_at.utcoffset() is not None, label
        assert r.object_type and r.object_id, label
        assert r.after is not None, (label, r.action)
    # 修改类动作必须带修改前值
    assert any(r.before is not None for r in rows if r.action in actions), label
    assert actor in {r.actor_name for r in rows if r.action in actions}, label


def test_rule_03_five_operations_audited(seeded, dingtalk, tmp_path):
    db = seeded
    g = G3(db, dingtalk, tmp_path)
    g.set_now("2026-12-01 09:00")
    lin = g.client("林晓")

    # 1. 角色分配修改：王浩的店铺范围增加 Amazon-CA-01
    mark = _max_id(db)
    wang = g.user("王浩")
    us, ca = g.store("Amazon-US-01"), g.store("Amazon-CA-01")
    r = lin.put(f"/api/admin/users/{wang.id}/roles", json={"roles": ["operations"], "stores": [us.id, ca.id]})
    assert r.status_code == 200, r.text
    rows = _new_audits(db, mark)
    _assert_complete(rows, actor="林晓", actions={rows[-1].action}, label="角色分配")
    role_row = rows[-1]
    assert role_row.object_type in ("user", "app_user", "user_role") and role_row.object_id == str(wang.id)
    assert "Amazon-CA-01" not in str(role_row.before) and str(ca.id) in str(role_row.after) or \
        "Amazon-CA-01" in str(role_row.after)
    # 恢复为契约种子范围（同样经接口，产生审计）
    assert lin.put(f"/api/admin/users/{wang.id}/roles", json={"roles": ["operations"],
                                                              "stores": [us.id]}).status_code == 200

    # 2. CEO 锁定年初原始目标
    c = TestClient(lin.app, base_url="http://testserver")
    task_id = publish(c, db, minimal_units(db)).json()["task"]["id"]
    for name, (filler, head, cell) in _cells(db).items():
        unit = unit_by_name(db, task_id, name)
        login(c, db, filler)
        assert save(c, unit.id, [cell]).json()["errors"] == []
        assert submit(c, unit.id).status_code == 200
        login(c, db, head)
        assert c.post(f"/api/approvals/unit/{unit.id}/approve").status_code == 200
    login(c, db, "linxiao")
    assert c.post(f"/api/tasks/{task_id}/submit-to-ceo").status_code == 200
    mark = _max_id(db)
    login(c, db, "zhoumingyuan")
    r = c.post(f"/api/approvals/task/{task_id}/approve")
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    rows = _new_audits(db, mark)
    v1 = db.scalar(select(BudgetVersion).where(BudgetVersion.year == 2027,
                                               BudgetVersion.type == VersionType.ORIGINAL_TARGET))
    assert v1 is not None and v1.locked
    lock_rows = [x for x in rows if x.actor_name == "周明远"]
    _assert_complete(lock_rows, actor="周明远", actions={x.action for x in lock_rows}, label="CEO 锁定")
    assert any(str(v1.id) == x.object_id or str(task_id) == x.object_id for x in lock_rows)

    # 3. 目标调整发起与审批（单位两级审核 + CEO 整次终审）
    g.set_now("2027-05-12 09:00")
    mark = _max_id(db)
    r = g.client("林晓").post("/api/versions/adjustments")
    assert r.status_code == 200, r.text
    adj_id = r.json()["id"]
    units = db.scalars(select(FillingUnit).where(FillingUnit.adjustment_id == adj_id)).all()
    for u in units:
        filler = db.get(User, u.filler_id).name
        r = g.client(filler).post(f"/api/versions/adjustments/units/{u.id}/submit",
                                  json={"adjust_reason": "Prime Day 提前至 6 月"})
        assert r.status_code == 200, r.text
    for u in units:
        reviewer = db.get(User, u.reviewer_id).name
        r = g.client(reviewer).post(f"/api/approvals/adjustment-unit/{u.id}/approve")
        assert r.status_code == 200, (reviewer, r.text)
    for u in units:
        r = g.client("林晓").post(f"/api/approvals/adjustment-unit/{u.id}/approve")
        assert r.status_code == 200, r.text
    r = g.client("周明远").post(f"/api/approvals/adjustment/{adj_id}/approve")
    assert r.status_code == 200, r.text
    rows = _new_audits(db, mark)
    acts = {x.action for x in rows}
    assert {"adjustment_started", "adjustment_unit_submitted", "adjustment_unit_approved",
            "adjustment_effective"} <= acts, acts
    _assert_complete(rows, actor="林晓", actions={"adjustment_started", "adjustment_unit_approved"}, label="目标调整")
    _assert_complete(rows, actor="周明远", actions={"adjustment_effective"}, label="目标调整生效")

    # 4. 金蝶导入与覆盖
    mark = _max_id(db)
    first = g.import_file(fixture_path("金蝶_2027-04_利润表.xlsx"), "kingdee")
    g.set_now("2027-05-13 10:00")
    second = g.import_file(fixture_path("金蝶_2027-04_利润表_v3.xlsx"), "kingdee", overwrite=True)
    rows = _new_audits(db, mark)
    _assert_complete(rows, actor="陈思雨", actions={x.action for x in rows if x.actor_name == "陈思雨"},
                     label="金蝶导入与覆盖")
    objs = {x.object_id for x in rows if x.actor_name == "陈思雨"}
    assert {str(first["id"]), str(second["id"])} <= objs, objs
    assert db.get(ImportBatch, first["id"]).status == "replaced"

    # 5. 规则新建与审批
    mark = _max_id(db)
    r = g.client("陈思雨").post("/api/rules", json={
        "type": "driver_assumption", "name": "Amazon 美国站 11 月销量为 10 月的 1.6 倍",
        "content_text": "Amazon 美国站 11 月销量 = 10 月 × 1.6", "credibility": "observed", "basis": "2025–2026 金蝶"})
    assert r.status_code == 200, r.text
    rv_id = r.json()["versions"][0]["id"]
    r = g.client("林晓").post(f"/api/approvals/rule-version/{rv_id}/approve")
    assert r.status_code == 200, r.text
    rows = _new_audits(db, mark)
    _assert_complete(rows, actor="陈思雨", actions={x.action for x in rows}, label="规则新建与审批")
    assert {x.actor_name for x in rows} == {"陈思雨", "林晓"}
    assert db.get(RuleVersion, rv_id).status == "effective"


# ---------------------------------------------------------------------------
# 同事务：业务回滚时无审计行（真实提交路径，不使用测试事务夹具）
# ---------------------------------------------------------------------------
ACC4_URL = "postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc4"


@pytest.fixture
def real_db():
    """真实提交路径：E4 应用库 budget_acc4 重建 + 种子（不污染共享测试库）。"""
    from tests.acceptance.e4_env import reset
    reset(url=ACC4_URL)
    eng = create_engine(ACC4_URL)
    yield eng
    eng.dispose()


@E4_LIVE
def test_rule_03_audit_rolls_back_with_business(real_db, dingtalk):
    app = create_app(make_settings(DATABASE_URL=ACC4_URL), dingtalk=dingtalk)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)
    with Session(real_db) as s:
        uid = {u.dingtalk_userid: u.id for u in s.scalars(select(User))}
        ca = s.scalar(select(Store.id).where(Store.name == "Amazon-CA-01"))
        us = s.scalar(select(Store.id).where(Store.name == "Amazon-US-01"))

    def state():
        with Session(real_db) as s:
            return (s.scalar(select(func.count()).select_from(AuditLog)),
                    sorted(s.scalars(select(UserScope.object_id).where(UserScope.user_id == uid["wanghao"]))),
                    s.scalar(select(func.count()).select_from(Rule)),
                    s.scalar(select(func.count()).select_from(RuleVersion)))

    def boom(*_a, **_k):  # 审计行 INSERT 已执行之后让业务失败
        raise RuntimeError("注入：审计写入后业务失败")

    def failing(call):
        before = state()
        event.listen(AuditLog, "after_insert", boom)
        try:
            r = call()
        finally:
            event.remove(AuditLog, "after_insert", boom)
        assert r.status_code == 500, r.text
        assert state() == before  # 审计行数、角色范围、规则行数全部不变

    assert client.post("/api/dev/login-as", json={"user_id": uid["linxiao"]}).status_code == 200
    failing(lambda: client.put(f"/api/admin/users/{uid['wanghao']}/roles",
                               json={"roles": ["operations"], "stores": [us, ca]}))
    assert client.post("/api/dev/login-as", json={"user_id": uid["chensiyu"]}).status_code == 200
    failing(lambda: client.post("/api/rules", json={"type": "driver_assumption", "name": "回滚验证规则",
                                                    "content_text": "Amazon 美国站 11 月销量 = 10 月 × 1.6",
                                                    "credibility": "observed", "basis": "2025 金蝶"}))

    # 不注入时同一操作正常提交：业务与审计同时出现
    assert client.post("/api/dev/login-as", json={"user_id": uid["linxiao"]}).status_code == 200
    n, scopes, *_ = state()
    r = client.put(f"/api/admin/users/{uid['wanghao']}/roles", json={"roles": ["operations"], "stores": [us, ca]})
    assert r.status_code == 200, r.text
    n2, scopes2, *_ = state()
    assert scopes == [us] and scopes2 == sorted([us, ca]) and n2 == n + 1


# ---------------------------------------------------------------------------
# 只追加：应用数据库账号 UPDATE / DELETE 报错且行数不变；无修改审计的 HTTP 接口；无自动清理任务
# ---------------------------------------------------------------------------
@E4_LIVE
def test_rule_03_append_only_and_no_http_or_cleanup(real_db, dingtalk):
    app = create_app(make_settings(DATABASE_URL=ACC4_URL), dingtalk=dingtalk)
    client = TestClient(app, base_url="http://testserver")
    with Session(real_db) as s:
        lin = s.scalar(select(User.id).where(User.dingtalk_userid == "linxiao"))
    assert client.post("/api/dev/login-as", json={"user_id": lin}).status_code == 200  # 真实提交的审计行
    dsn = ACC4_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as conn:  # 应用数据库账号 budget（非超级用户）
        assert conn.execute("SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user").fetchone() \
            == ("budget", False)
        n0 = conn.execute("SELECT count(*) FROM audit_log").fetchone()[0]
        for sql in ("UPDATE audit_log SET actor_name = '篡改'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
            with pytest.raises(psycopg.Error) as e:
                conn.execute(sql)
            conn.rollback()
            assert e.value.sqlstate in ("BG003", "42501"), (sql, e.value.sqlstate)
        assert conn.execute("SELECT count(*) FROM audit_log").fetchone()[0] == n0
        privs = conn.execute("SELECT has_table_privilege('audit_log', 'UPDATE'), "
                             "has_table_privilege('audit_log', 'DELETE'), has_table_privilege('audit_log', 'INSERT'), "
                             "has_table_privilege('audit_log', 'SELECT')").fetchone()
        assert privs == (False, False, True, True)
    assert n0 > 0

    # HTTP：注册表中没有任何审计路由，DELETE 方法路由只有未知路径 404 兜底
    paths = [(sorted(r.methods), r.path) for r in iter_api_routes(app)]
    assert not [p for p in paths if "audit" in p[1].lower()]
    assert [p for m, p in paths if "DELETE" in m] == ["/api/{rest:path}"]
    for method in ("GET", "DELETE", "PUT", "PATCH"):
        assert client.request(method, "/api/audit-logs").status_code == 404
    # 应用代码中没有对审计表的修改 / 删除语句
    src = "\n".join(p.read_text(encoding="utf-8") for p in (BACKEND / "app").rglob("*.py"))
    assert not re.search(r"(update|delete)\(\s*AuditLog", src, re.I)
    assert not re.search(r"(UPDATE|DELETE\s+FROM|TRUNCATE)\s+audit_log", src)
    # 调度器只有发件箱、逾期检查与通讯录同步，没有清理任务
    jobs = re.findall(r'id="([a-z_]+)"', inspect.getsource(scheduler_mod))
    assert sorted(jobs) == ["contacts_full", "contacts_incremental", "outbox", "overdue"]
