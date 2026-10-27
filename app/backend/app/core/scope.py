"""数据范围过滤 CMP-F01-03（DEC-009、NFR-003）。

用法（路由）：
    @router.get("/xxx")
    def handler(ctx: ScopeContext = Depends(get_scope), db: Session = Depends(get_db)):
        q = select(PlatformUnit).where(ctx.store_clause(PlatformUnit.store_id, PlatformUnit.channel_id))
    @router.put("/yyy", dependencies=[Depends(require_roles(Role.FINANCE_BP))])

- CEO、财务负责人、财务BP 为全公司范围（AC-F01-10）。
- 每次请求重新加载角色与范围（不缓存在会话中），分配后下一次请求即生效（AC-F01-04）。
- 详情与写操作：取到记录后调用 ensure_*；不在范围内抛 Forbidden（403「无权限」，不带记录字段）。
- 字段级：物流物控只见维度列与四项物流比例（AC-F01-09），用 logistics_view() 在序列化前裁剪。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends
from sqlalchemy import ColumnElement, false, or_, select, true
from sqlalchemy.orm import Session

from app.core.auth import CurrentUser, get_current_user
from app.core.errors import Forbidden
from app.db import get_db
from app.models import BCustomer, Store, UserScope
from app.models.enums import Role, ScopeType

# 物流物控可见 / 可编辑的四项比例（头程、尾程、仓储、关税）
LOGISTICS_RATE_FIELDS = ("first_leg_rate", "last_mile_rate", "storage_rate", "tariff_rate")
# 维度列：任何角色视图都可保留
DIMENSION_FIELDS = ("id", "version_id", "month", "channel_id", "channel_name", "store_id", "store_name", "site_id",
                    "site_name", "category_id", "category_name", "is_new", "customer_id", "customer_name",
                    "department_id", "department_name", "currency", "updated_by", "updated_by_name", "updated_at")


@dataclass(frozen=True)
class ScopeContext:
    user_id: int
    roles: frozenset[str]
    department_ids: frozenset[int] = field(default_factory=frozenset)
    channel_ids: frozenset[int] = field(default_factory=frozenset)
    store_ids: frozenset[int] = field(default_factory=frozenset)      # 显式店铺 + 渠道展开后的店铺
    customer_ids: frozenset[int] = field(default_factory=frozenset)

    # ---- 角色判断 ----
    @property
    def all_company(self) -> bool:
        return bool(self.roles & Role.ALL_COMPANY)

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles & set(roles))

    @property
    def logistics_only_fields(self) -> bool:
        """物流物控（且无全公司角色）：只能看维度列与四项物流比例。"""
        return Role.LOGISTICS in self.roles and not self.all_company and not (
            self.roles & {Role.OPERATIONS, Role.B2B})

    # ---- 查询条件 ----
    def department_clause(self, column) -> ColumnElement[bool]:
        if self.all_company:
            return true()
        return column.in_(self.department_ids) if self.department_ids else false()

    def store_clause(self, store_column, channel_column=None) -> ColumnElement[bool]:
        """店铺范围：店铺 ID ∈ 范围（渠道范围已展开为店铺），可选再按渠道列匹配。"""
        if self.all_company:
            return true()
        parts = []
        if self.store_ids:
            parts.append(store_column.in_(self.store_ids))
        if channel_column is not None and self.channel_ids:
            parts.append(channel_column.in_(self.channel_ids))
        return or_(*parts) if parts else false()

    def customer_clause(self, column) -> ColumnElement[bool]:
        if self.all_company:
            return true()
        return column.in_(self.customer_ids) if self.customer_ids else false()

    # ---- 单条记录检查 ----
    def ensure_roles(self, *roles: str) -> None:
        if not self.has_role(*roles):
            raise Forbidden()

    def ensure_department(self, department_id: int | None) -> None:
        if not self.all_company and department_id not in self.department_ids:
            raise Forbidden()

    def ensure_store(self, store_id: int | None, channel_id: int | None = None) -> None:
        if self.all_company:
            return
        if store_id in self.store_ids or (channel_id is not None and channel_id in self.channel_ids):
            return
        raise Forbidden()

    def ensure_customer(self, customer_id: int | None) -> None:
        if not self.all_company and customer_id not in self.customer_ids:
            raise Forbidden()

    def summary(self) -> dict[str, list[int]]:
        return {
            "departments": sorted(self.department_ids),
            "channels": sorted(self.channel_ids),
            "stores": sorted(self.store_ids),
            "customers": sorted(self.customer_ids),
        }


def load_scope(db: Session, user_id: int, roles: Iterable[str]) -> ScopeContext:
    rows = db.execute(select(UserScope.scope_type, UserScope.object_id).where(UserScope.user_id == user_id)).all()
    by_type: dict[str, set[int]] = {t: set() for t in ScopeType.ALL}
    for scope_type, object_id in rows:
        by_type[scope_type].add(object_id)
    stores = set(by_type[ScopeType.STORE])
    if by_type[ScopeType.CHANNEL]:
        stores |= set(db.scalars(select(Store.id).where(Store.channel_id.in_(by_type[ScopeType.CHANNEL]))))
    customers = set(by_type[ScopeType.CUSTOMER])
    if customers and Role.B2B in set(roles):
        # B 端业务按所负责客户的部门（其 B 端填报单位）看全部客户，之后新增的客户自动纳入（AC-F02-09，同渠道含新店铺）
        depts = select(BCustomer.department_id).where(BCustomer.id.in_(customers))
        customers |= set(db.scalars(select(BCustomer.id).where(BCustomer.department_id.in_(depts))))
    return ScopeContext(
        user_id=user_id,
        roles=frozenset(roles),
        department_ids=frozenset(by_type[ScopeType.DEPARTMENT]),
        channel_ids=frozenset(by_type[ScopeType.CHANNEL]),
        store_ids=frozenset(stores),
        customer_ids=frozenset(customers),
    )


def get_scope(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> ScopeContext:
    return load_scope(db, current.user.id, current.roles)


def require_roles(*roles: str):
    """路由依赖：当前用户至少拥有其中一个角色，否则 403「无权限」。"""
    allowed = frozenset(roles)

    def _dep(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not (current.roles & allowed):
            raise Forbidden()
        return current

    _dep.required_roles = allowed  # 供路由权限声明检查使用
    return _dep


def logistics_view(row: Mapping[str, Any], extra_dims: Iterable[str] = ()) -> dict[str, Any]:
    """物流物控字段级视图：只保留维度列与四项物流比例，收入、销量、利润等键在序列化前就不存在。"""
    keep = set(DIMENSION_FIELDS) | set(extra_dims) | set(LOGISTICS_RATE_FIELDS)
    return {k: v for k, v in row.items() if k in keep}


def restrict_fields(ctx: ScopeContext, row: Mapping[str, Any], extra_dims: Iterable[str] = ()) -> dict[str, Any]:
    """按角色裁剪字段：物流物控用 logistics_view，其余角色原样返回。"""
    return logistics_view(row, extra_dims) if ctx.logistics_only_fields else dict(row)


def ensure_writable_fields(ctx: ScopeContext, fields: Iterable[str]) -> None:
    """物流物控只能写四项物流比例，写其他字段 403。"""
    if ctx.logistics_only_fields and not set(fields) <= set(LOGISTICS_RATE_FIELDS):
        raise Forbidden()
