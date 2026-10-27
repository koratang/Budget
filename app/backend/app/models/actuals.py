"""DATA-F09-* 实际数导入：批次、暂存、金蝶实际、BI 明细与归集；DATA-F10-01 偏差说明。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Amount, Base, Price
from app.models.enums import ImportSource, ImportStatus, check_in

_SOURCES = (ImportSource.KINGDEE, ImportSource.KINGDEE_HISTORY, ImportSource.BI, ImportSource.SKU,
            ImportSource.TEMPLATE)


class ImportBatch(Base):
    """导入批次。BI / 历史文件按期间拆为逻辑批次（parent_batch_id 指向上传批次）。
    覆盖导入：旧批次标「已被替换」并记录替换批次，行数据保留但不参与计算。"""
    __tablename__ = "import_batch"
    __table_args__ = (
        CheckConstraint(check_in("source", _SOURCES), name="source"),
        CheckConstraint(check_in("status", ImportStatus.LABELS), name="status"),
        CheckConstraint("period IS NULL OR extract(day from period) = 1", name="period_first_day"),
        Index("ix_import_batch_source_period_status", "source", "period", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    period: Mapped[date | None] = mapped_column(Date)  # 逻辑批次的期间（月初）
    parent_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    file_path: Mapped[str | None] = mapped_column(String(512))
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=ImportStatus.VALIDATING)
    errors: Mapped[list | None] = mapped_column(JSONB)  # [{row, type, value, message}]
    row_count: Mapped[int | None] = mapped_column(Integer)
    replaced_by_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("filling_unit.id"))  # 填报模板上传
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))


class ImportStaging(Base):
    """导入暂存（确认后清理，DEC-008）。"""
    __tablename__ = "import_staging"
    __table_args__ = (UniqueConstraint("batch_id", "row_no"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id", ondelete="CASCADE"), nullable=False)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)


class KingdeeActual(Base):
    """金蝶实际：带客户辅助核算且客户在主数据中时记入该客户；无店铺且非部门费用科目的成本费用行 unassigned。"""
    __tablename__ = "kingdee_actual"
    __table_args__ = (
        CheckConstraint("extract(day from month) = 1", name="month_first_day"),
        Index("ix_kingdee_actual_month", "month"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id"), nullable=False, index=True)
    row_no: Mapped[int | None] = mapped_column(Integer)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("department.id"))
    store_id: Mapped[int | None] = mapped_column(ForeignKey("store.id"))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("site.id"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("b_customer.id"))
    kingdee_code: Mapped[str] = mapped_column(String(32), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("budget_account.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    unassigned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    summary: Mapped[str | None] = mapped_column(String(256))


class BiActualSku(Base):
    """BI 明细：批次、月、店铺、站点、SKU、销量、本币销售额、币种、广告费、平台费。"""
    __tablename__ = "bi_actual_sku"
    __table_args__ = (
        CheckConstraint("extract(day from month) = 1", name="month_first_day"),
        Index("ix_bi_actual_sku_month_store", "month", "store_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id"), nullable=False, index=True)
    row_no: Mapped[int | None] = mapped_column(Integer)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("store.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"), nullable=False)
    sku_id: Mapped[int] = mapped_column(ForeignKey("sku.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Price, nullable=False)
    sales_local: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    ad_fee: Mapped[Decimal | None] = mapped_column(Amount)
    platform_fee: Mapped[Decimal | None] = mapped_column(Amount)


class BiActualAgg(Base):
    """BI 归集：月 × 店铺 × 站点 × 品类 × 新老品（导入时按当时的 SKU 对照表归集，之后不回改）。"""
    __tablename__ = "bi_actual_agg"
    __table_args__ = (
        UniqueConstraint("batch_id", "month", "store_id", "site_id", "category_id", "is_new", name="uq_bi_agg_key"),
        CheckConstraint("extract(day from month) = 1", name="month_first_day"),
        Index("ix_bi_actual_agg_month_store", "month", "store_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batch.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("store.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), nullable=False)
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False)
    spu_count: Mapped[int] = mapped_column(Integer, nullable=False)
    qty: Mapped[Decimal] = mapped_column(Price, nullable=False)
    revenue_local: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    revenue_cny: Mapped[Decimal | None] = mapped_column(Amount)  # 缺当月平均汇率时为空


class VarianceNote(Base):
    """DATA-F10-01 偏差说明：只保留最新一条，修改记录进入审计日志。"""
    __tablename__ = "variance_note"
    __table_args__ = (
        UniqueConstraint("report_type", "month", "object_type", "object_key", name="uq_variance_note_key"),
        CheckConstraint("extract(day from month) = 1", name="month_first_day"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    report_type: Mapped[str] = mapped_column(String(24), nullable=False)  # channel-site / category / dept-expense
    month: Mapped[date] = mapped_column(Date, nullable=False)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False)
    object_key: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
