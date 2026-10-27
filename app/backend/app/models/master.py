"""DATA-F02-* 主数据：渠道/店铺/站点、部门/B 端客户、预算科目/科目映射、品类/SPU/SKU、汇率。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, FxRate, created_at_col


class Channel(Base):
    __tablename__ = "channel"
    __table_args__ = (
        CheckConstraint("new_channel_start IS NULL OR extract(day from new_channel_start) = 1",
                        name="start_first_day"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_new_channel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    new_channel_start: Mapped[date | None] = mapped_column(Date)  # 新渠道起始月（月初）
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class Site(Base):
    """站点：US 美国、CA 加拿大、UK 英国、DE 德国……"""
    __tablename__ = "site"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)


class Store(Base):
    __tablename__ = "store"
    __table_args__ = (
        # 供预算单元以复合外键保证「店铺属于该渠道、站点为该店铺站点」
        UniqueConstraint("id", "channel_id", name="uq_store_id_channel"),
        UniqueConstraint("id", "site_id", name="uq_store_id_site"),
        CheckConstraint("new_channel_start IS NULL OR extract(day from new_channel_start) = 1",
                        name="start_first_day"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channel.id"), nullable=False, index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_new_channel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    new_channel_start: Mapped[date | None] = mapped_column(Date)


class Department(Base):
    __tablename__ = "department"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    head_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id", use_alter=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class BCustomer(Base):
    __tablename__ = "b_customer"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class BudgetAccount(Base):
    """预算科目：只停用不删除；数据行以 ID 关联，改名不影响历史。"""
    __tablename__ = "budget_account"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_dept_expense: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 非部门费用科目在损益中的口径（revenue/refund/purchase_cost/commission/promotion/first_leg/
    # last_mile/tariff/storage/inventory_claim/other_opex/finance_cost/fx_gain_loss/non_operating/income_tax）
    pl_item: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class KingdeeAccountMap(Base):
    """金蝶科目编码 → 预算科目（只改不删；修改只影响之后的导入）。"""
    __tablename__ = "kingdee_account_map"
    id: Mapped[int] = mapped_column(primary_key=True)
    kingdee_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    kingdee_name: Mapped[str | None] = mapped_column(String(128))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("budget_account.id"))  # 空 = 未映射
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Category(Base):
    __tablename__ = "category"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class Spu(Base):
    """SPU：首次上架日期 = 其下 SKU 上架日期最小值（上传事务内重算，DEC-021）。"""
    __tablename__ = "spu"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), nullable=False, index=True)
    first_listed_on: Mapped[date] = mapped_column(Date, nullable=False)


class Sku(Base):
    """SKU 只增改不删。"""
    __tablename__ = "sku"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    spu_id: Mapped[int] = mapped_column(ForeignKey("spu.id"), nullable=False, index=True)
    listed_on: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FxBudget(Base):
    """年度 × 币种预算汇率。年度存在年初原始目标即锁定：触发器禁止 UPDATE/DELETE，允许新增尚无汇率的币种（DEC-020）。"""
    __tablename__ = "fx_budget"
    __table_args__ = (UniqueConstraint("year", "currency"), CheckConstraint("rate > 0", name="rate_positive"))
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(FxRate, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FxActual(Base):
    """月 × 币种当月平均汇率（> 0，最多 4 位小数）。"""
    __tablename__ = "fx_actual"
    __table_args__ = (
        UniqueConstraint("month", "currency"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("rate = round(rate, 4)", name="rate_4dp"),
        CheckConstraint("extract(day from month) = 1", name="month_first_day"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(FxRate, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = created_at_col()
