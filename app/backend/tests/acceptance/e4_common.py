"""E4（RULE-01~09）验收共用：按 userid 登录的客户端、路由注册表遍历、整表快照。

测试库：TEST_DATABASE_URL=postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_test_acc4
（tests/conftest.py 的 db / seeded / dingtalk / stub 夹具：真实路由、权限与 PostgreSQL，每个测试事务回滚）。
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi.routing import APIRoute, _IncludedRouter
from sqlalchemy import select, text

from app.core.auth import get_current_user
from app.core.scope import get_scope
from app.models import User
from tests.conftest import build_client

FORBIDDEN_BODY = {"code": "forbidden", "message": "无权限"}


def uid(db, userid: str) -> int:
    return db.scalar(select(User.id).where(User.dingtalk_userid == userid))


def client_as(db, dingtalk, userid: str, **settings):
    c = build_client(db, dingtalk, **settings)
    r = c.post("/api/dev/login-as", json={"user_id": uid(db, userid)})
    assert r.status_code == 200, r.text
    return c


def iter_api_routes(app) -> Iterator[APIRoute]:
    """遍历应用的路由注册表（含 include_router 挂载的全部路由）。"""
    for r in app.routes:
        if isinstance(r, _IncludedRouter):
            yield from r.effective_route_contexts()
        elif isinstance(r, APIRoute):
            yield r


def dependency_calls(route) -> list:
    out = []

    def walk(d):
        for sub in d.dependencies:
            out.append(sub.call)
            walk(sub)

    walk(route.dependant)
    return out


def route_guard(route) -> tuple[bool, frozenset[str] | None, bool]:
    """(是否声明认证依赖, require_roles 声明的角色集合, 是否声明数据范围依赖 get_scope)。"""
    calls = dependency_calls(route)
    roles = None
    for c in calls:
        if hasattr(c, "required_roles"):
            roles = (roles or frozenset()) | c.required_roles
    return get_current_user in calls, roles, get_scope in calls


def table_snapshot(db, tables: list[str]) -> dict:
    """各表行数与整表校验和（整行文本 md5 聚合）。"""
    out = {}
    for t in tables:
        out[t] = tuple(db.execute(text(
            f"SELECT count(*), coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '') FROM {t} x")).one())
    return out


def business_tables(db) -> list[str]:
    """public 下全部业务表（不含迁移版本表与会话表；会话随登录变化，不属业务数据）。"""
    names = db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")).all()
    return [n for n in names if n not in ("alembic_version", "user_session")]
