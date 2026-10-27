"""角色与数据范围分配（REQ-F01-02、AC-F01-04/05；DEC-019、DEC-009）。

- 员工来自钉钉通讯录（app_user），本模块只分配角色与范围，不新增 / 停用员工。
- 保存即替换该员工的全部角色与范围；范围只保留与所选角色相关的部分。
- 结果会使启用的财务负责人数量为 0 时拒绝（409 last_finance_head），不写入。
- 范围不缓存：被分配员工下一次请求时由 ScopeContext 重新加载（AC-F01-04）。
本模块只 flush 不 commit，由路由写审计后统一提交。
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, ValidationFailed
from app.models import BCustomer, Channel, Department, Store, User, UserRole, UserScope
from app.models.enums import Role, ScopeType

LAST_FINANCE_HEAD_MESSAGE = "系统至少需要保留一名财务负责人"
DEPT_ROLES = frozenset({Role.DEPT_HEAD, Role.DEPT_BUDGET})
PAGE_SIZE = 50


def _roles_by_user(db: Session) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for uid, code in db.execute(select(UserRole.user_id, UserRole.role_code)):
        out.setdefault(uid, set()).add(code)
    return out


def _scopes_by_user(db: Session) -> dict[int, dict[str, list[int]]]:
    out: dict[int, dict[str, list[int]]] = {}
    for uid, t, oid in db.execute(select(UserScope.user_id, UserScope.scope_type, UserScope.object_id)
                                  .order_by(UserScope.object_id)):
        out.setdefault(uid, {k: [] for k in ScopeType.ALL})[t].append(oid)
    return out


def _empty_scopes() -> dict[str, list[int]]:
    return {k: [] for k in ScopeType.ALL}


def user_payload(user: User, roles: set[str], scopes: dict[str, list[int]]) -> dict:
    ordered = [r for r in Role.ALL if r in roles]
    return {
        "id": user.id, "name": user.name, "dingtalk_userid": user.dingtalk_userid,
        "dingtalk_dept": user.dingtalk_dept, "is_active": user.is_active,
        "roles": ordered, "role_names": [Role.LABELS[r] for r in ordered],
        "scopes": {"departments": scopes[ScopeType.DEPARTMENT], "channels": scopes[ScopeType.CHANNEL],
                   "stores": scopes[ScopeType.STORE], "customers": scopes[ScopeType.CUSTOMER]},
    }


def list_users(db: Session, q: str | None = None, dept: str | None = None, role: str | None = None,
               unassigned: bool = False, page: int = 1, page_size: int = PAGE_SIZE) -> dict:
    roles = _roles_by_user(db)
    scopes = _scopes_by_user(db)
    users = db.scalars(select(User).order_by(User.id)).all()
    all_items = [user_payload(u, roles.get(u.id, set()), scopes.get(u.id, _empty_scopes())) for u in users]
    filtered = [i for i in all_items
                if (not q or q.strip() in i["name"])
                and (not dept or i["dingtalk_dept"] == dept)
                and (not role or role in i["roles"])
                and (not unassigned or not i["roles"])]
    start = (page - 1) * page_size
    assigned = sum(1 for i in all_items if i["roles"])
    order = _dept_order(db)
    return {
        "items": filtered[start:start + page_size],
        "total": len(filtered), "page": page, "page_size": page_size,
        "summary": {"employees": len(all_items), "assigned": assigned, "unassigned": len(all_items) - assigned},
        "dingtalk_depts": sorted({u.dingtalk_dept for u in users if u.dingtalk_dept},
                                 key=lambda n: order.get(n, 999)),
    }


def _dept_order(db: Session) -> dict[str, int]:
    return {name: i for i, name in enumerate(db.scalars(select(Department.name)
                                                         .order_by(Department.sort, Department.id)))}


def scope_options(db: Session) -> dict:
    """分配抽屉的范围选项：部门、渠道 → 店铺（含停用店铺，标「已停用」）、B 端客户。"""
    depts = db.scalars(select(Department).order_by(Department.sort, Department.id)).all()
    channels = db.scalars(select(Channel).order_by(Channel.sort, Channel.id)).all()
    stores = db.scalars(select(Store).order_by(Store.id)).all()
    dept_names = {d.id: d.name for d in depts}
    return {
        "roles": [{"code": r, "name": Role.LABELS[r]} for r in Role.ALL],
        "departments": [{"id": d.id, "name": d.name, "is_active": d.is_active} for d in depts],
        "channels": [{"id": c.id, "name": c.name,
                      "stores": [{"id": s.id, "name": s.name, "is_active": s.is_active}
                                 for s in stores if s.channel_id == c.id]} for c in channels],
        "customers": [{"id": c.id, "name": c.name, "department_name": dept_names.get(c.department_id),
                       "currency": c.currency, "is_active": c.is_active}
                      for c in db.scalars(select(BCustomer).order_by(BCustomer.id))],
    }


def _active_finance_heads(db: Session) -> set[int]:
    return set(db.scalars(select(User.id).join(UserRole, UserRole.user_id == User.id)
                          .where(UserRole.role_code == Role.FINANCE_HEAD, User.is_active.is_(True))))


def _existing_ids(db: Session, model, ids: list[int]) -> list[int]:
    ids = sorted(set(ids))
    if not ids:
        return []
    found = set(db.scalars(select(model.id).where(model.id.in_(ids))))
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValidationFailed("所选范围对象不存在", details={"missing": missing})
    return ids


def snapshot(db: Session, user_id: int) -> dict:
    roles = sorted(db.scalars(select(UserRole.role_code).where(UserRole.user_id == user_id)))
    scopes = _empty_scopes()
    for t, oid in db.execute(select(UserScope.scope_type, UserScope.object_id)
                             .where(UserScope.user_id == user_id).order_by(UserScope.object_id)):
        scopes[t].append(oid)
    return {"roles": roles, "scopes": scopes}


def save_user_roles(db: Session, user: User, roles: list[str], departments: list[int], channels: list[int],
                    stores: list[int], customers: list[int]) -> tuple[dict, dict]:
    """替换该员工的角色与范围；返回 (修改前, 修改后) 供审计。roles 为空表示撤销全部角色。"""
    unknown = [r for r in roles if r not in Role.LABELS]
    if unknown:
        raise ValidationFailed("角色不存在", details={"roles": unknown})
    role_set = set(roles)
    if role_set and not user.is_active:
        raise Conflict("该员工钉钉账号已停用，无法登录，不能分配角色", code="account_disabled")
    errors: dict[str, str] = {}
    if role_set & DEPT_ROLES and not departments:
        errors["departments"] = "请选择至少一个部门"
    if Role.OPERATIONS in role_set and not (channels or stores):
        errors["stores"] = "请选择至少一个渠道或店铺"
    if Role.B2B in role_set and not customers:
        errors["customers"] = "请选择至少一个 B端客户"
    if errors:
        raise ValidationFailed(next(iter(errors.values())), code="scope_required", details={"fields": errors})

    heads = _active_finance_heads(db)
    if user.id in heads and Role.FINANCE_HEAD not in role_set and len(heads) == 1:
        raise Conflict(LAST_FINANCE_HEAD_MESSAGE, code="last_finance_head")

    new_scopes = {
        ScopeType.DEPARTMENT: _existing_ids(db, Department, departments) if role_set & DEPT_ROLES else [],
        ScopeType.CHANNEL: _existing_ids(db, Channel, channels) if Role.OPERATIONS in role_set else [],
        ScopeType.STORE: _existing_ids(db, Store, stores) if Role.OPERATIONS in role_set else [],
        ScopeType.CUSTOMER: _existing_ids(db, BCustomer, customers) if Role.B2B in role_set else [],
    }
    # 勾选整个渠道时只存渠道范围（之后新增的店铺自动包含，PAGE-F01-02 Q4），不重复存其店铺
    if new_scopes[ScopeType.CHANNEL]:
        covered = set(db.scalars(select(Store.id).where(Store.channel_id.in_(new_scopes[ScopeType.CHANNEL]))))
        new_scopes[ScopeType.STORE] = [s for s in new_scopes[ScopeType.STORE] if s not in covered]

    before = snapshot(db, user.id)
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.execute(delete(UserScope).where(UserScope.user_id == user.id))
    db.flush()
    db.add_all([UserRole(user_id=user.id, role_code=r) for r in Role.ALL if r in role_set])
    db.add_all([UserScope(user_id=user.id, scope_type=t, object_id=oid)
                for t, ids in new_scopes.items() for oid in ids])
    db.flush()
    return before, snapshot(db, user.id)

