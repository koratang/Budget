"""模型基类与公用列类型（技术方案 §4.3 列精度）。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, MetaData, Numeric, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# 列精度（DEC-005）
Ratio = Numeric(9, 6)        # 比率小数：12.3456% 存 0.123456
Price = Numeric(18, 4)       # 平均单价、平均销量
Amount = Numeric(20, 6)      # 本币 / 人民币金额（保留未舍入值）
FxRate = Numeric(12, 6)      # 汇率
Margin = Numeric(12, 8)      # 毛利率等派生比率
Metric = Numeric(20, 8)      # 预警指标值等


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def ratio_col(**kw) -> Mapped[Decimal]:
    return mapped_column(Ratio, nullable=False, server_default="0", default=Decimal(0), **kw)


def amount_col(nullable: bool = True, **kw) -> Mapped[Decimal | None]:
    return mapped_column(Amount, nullable=nullable, **kw)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_by_col():
    return mapped_column(ForeignKey("app_user.id"), nullable=True)


def updated_at_col():
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
