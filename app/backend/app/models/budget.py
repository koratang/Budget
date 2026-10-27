"""编制任务、版本、填报单位与预算数据（DATA-F03/F04/F05/F06/F07/F08）。

所有预算数据表以 version_id 为首列；锁定版本（locked = true）下的行由触发器禁止增删改（DEC-016）。
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index,
                        Integer, SmallInteger, String, Text, UniqueConstraint, func, text)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (Amount, Base, Margin, Price, amount_col, created_at_col, ratio_col, updated_at_col,
                             updated_by_col)
from app.models.enums import (AdjustmentStatus, OtherPlItem, TaskStatus, UnitStatus, UnitType, VersionType,
                              check_in)

MONTH_CHECK = "extract(day from month) = 1"



class BudgetVersion(Base):
    """DATA-F08-01 预算版本：只增不改；locked 后由触发器禁止修改。"""
    __tablename__ = "budget_version"
    __table_args__ = (
        CheckConstraint(check_in("type", VersionType.LABELS), name="type"),
        CheckConstraint("quarter IS NULL OR quarter BETWEEN 1 AND 4", name="quarter"),
        UniqueConstraint("year", "type", "version_no"),
        # 同一季度滚动更新只能发起一次（滚动预测稿发布后转为季度快照）
        Index("uq_budget_version_rolling_quarter", "year", "quarter", unique=True,
              postgresql_where=text("type IN ('rolling_draft', 'snapshot')")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    quarter: Mapped[int | None] = mapped_column(SmallInteger)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    adjust_reason: Mapped[str | None] = mapped_column(Text)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    published_on: Mapped[date | None] = mapped_column(Date)
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("budget_version.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = created_at_col()


class BudgetTask(Base):
    """DATA-F03-01 编制任务：同年度未完成（进行中 / 待CEO审批）任务唯一。"""
    __tablename__ = "budget_task"
    __table_args__ = (
        CheckConstraint(check_in("status", TaskStatus.LABELS), name="status"),
        Index("uq_budget_task_open_year", "year", unique=True,
              postgresql_where=text("status IN ('in_progress', 'pending_ceo')")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=TaskStatus.IN_PROGRESS)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    ceo_return_reason: Mapped[str | None] = mapped_column(Text)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = created_at_col()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TargetAdjustment(Base):
    """DATA-F08-03 目标调整：同年度进行中至多一个；同年度同季度已生效至多一个（DEC-022）。"""
    __tablename__ = "target_adjustment"
    __table_args__ = (
        CheckConstraint(check_in("status", AdjustmentStatus.LABELS), name="status"),
        CheckConstraint("quarter BETWEEN 1 AND 4", name="quarter"),
        Index("uq_target_adjustment_open_year", "year", unique=True,
              postgresql_where=text("status IN ('in_progress', 'pending_ceo')")),
        Index("uq_target_adjustment_effective_quarter", "year", "quarter", unique=True,
              postgresql_where=text("status = 'effective'")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=AdjustmentStatus.IN_PROGRESS)
    draft_version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    result_version_id: Mapped[int | None] = mapped_column(ForeignKey("budget_version.id"))
    initiated_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    ceo_return_reason: Mapped[str | None] = mapped_column(Text)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


class FillingUnit(Base):
    """DATA-F03-02 填报单位：task_id / adjustment_id 二选一。"""
    __tablename__ = "filling_unit"
    __table_args__ = (
        CheckConstraint("(task_id IS NULL) <> (adjustment_id IS NULL)", name="task_xor_adjustment"),
        CheckConstraint(check_in("unit_type", UnitType.LABELS), name="unit_type"),
        CheckConstraint(check_in("status", UnitStatus.LABELS), name="status"),
        # 部分唯一索引：编制单位与调整单位各自唯一（另一外键恒为 NULL，不能参与比较，否则跨任务 / 跨季度调整冲突）
        Index("uq_filling_unit_task_scope", "task_id", "unit_type", "scope_object_id", unique=True,
              postgresql_nulls_not_distinct=True, postgresql_where=text("task_id IS NOT NULL")),
        Index("uq_filling_unit_adjustment_scope", "adjustment_id", "unit_type", "scope_object_id", unique=True,
              postgresql_nulls_not_distinct=True, postgresql_where=text("adjustment_id IS NOT NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("budget_task.id"), index=True)
    adjustment_id: Mapped[int | None] = mapped_column(ForeignKey("target_adjustment.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    unit_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 平台渠道 = 店铺 ID；B 端 / 部门费用 = 部门 ID；成本比例 / 物流比例 = 空
    scope_object_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    filler_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=UnitStatus.NOT_STARTED)
    return_reason: Mapped[str | None] = mapped_column(Text)
    adjust_reason: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PlatformUnit(Base):
    """DATA-F04-01 平台渠道预算单元：版本 × 月 × 渠道 × 店铺 × 站点 × 品类 × 新老品。"""
    __tablename__ = "platform_unit"
    __table_args__ = (
        UniqueConstraint("version_id", "month", "channel_id", "store_id", "site_id", "category_id", "is_new",
                         name="uq_platform_unit_key"),
        ForeignKeyConstraint(["store_id", "channel_id"], ["store.id", "store.channel_id"],
                             name="fk_platform_unit_store_channel"),
        ForeignKeyConstraint(["store_id", "site_id"], ["store.id", "store.site_id"],
                             name="fk_platform_unit_store_site"),
        CheckConstraint(MONTH_CHECK, name="month_first_day"),
        CheckConstraint("spu_count >= 0 AND avg_sales >= 0 AND avg_price >= 0", name="drivers_non_negative"),
        CheckConstraint("discount_rate BETWEEN 0 AND 1 AND refund_rate BETWEEN 0 AND 1 "
                        "AND ad_rate BETWEEN 0 AND 1 AND commission_rate BETWEEN 0 AND 1", name="rates_range"),
        Index("ix_platform_unit_version_store_month", "version_id", "store_id", "month"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channel.id"), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("store.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), nullable=False)
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # 七个驱动（运营）
    spu_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    avg_sales: Mapped[Decimal] = mapped_column(Price, nullable=False, default=Decimal(0), server_default="0")
    avg_price: Mapped[Decimal] = mapped_column(Price, nullable=False, default=Decimal(0), server_default="0")
    discount_rate: Mapped[Decimal] = ratio_col()
    refund_rate: Mapped[Decimal] = ratio_col()
    ad_rate: Mapped[Decimal] = ratio_col()
    commission_rate: Mapped[Decimal] = ratio_col()
    # 派生值（保存时由计算引擎写回）
    sales_qty: Mapped[Decimal | None] = amount_col()
    revenue_local: Mapped[Decimal | None] = amount_col()
    revenue_cny: Mapped[Decimal | None] = amount_col()
    refund: Mapped[Decimal | None] = amount_col()
    purchase_cost: Mapped[Decimal | None] = amount_col()
    commission: Mapped[Decimal | None] = amount_col()
    promotion: Mapped[Decimal | None] = amount_col()
    first_leg: Mapped[Decimal | None] = amount_col()
    last_mile: Mapped[Decimal | None] = amount_col()
    tariff: Mapped[Decimal | None] = amount_col()
    storage: Mapped[Decimal | None] = amount_col()
    inventory_claim: Mapped[Decimal | None] = amount_col()
    other_opex: Mapped[Decimal | None] = amount_col()
    gross_profit: Mapped[Decimal | None] = amount_col()
    gross_margin: Mapped[Decimal | None] = mapped_column(Margin)
    # 新渠道放量（DEC-023）：该店铺该月超出上限时全部单元 over_limit = true，理由写在同店铺同月全部单元
    over_limit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    over_limit_reason: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[int | None] = updated_by_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ChannelCategoryRatio(Base):
    """DATA-F04-02 渠道品类成本比例：版本 × 月 × 渠道 × 站点 × 品类。"""
    __tablename__ = "channel_category_ratio"
    __table_args__ = (
        UniqueConstraint("version_id", "month", "channel_id", "site_id", "category_id", name="uq_ccr_key"),
        CheckConstraint(MONTH_CHECK, name="month_first_day"),
        CheckConstraint("purchase_cost_rate BETWEEN 0 AND 1 AND first_leg_rate BETWEEN 0 AND 1 AND "
                        "last_mile_rate BETWEEN 0 AND 1 AND storage_rate BETWEEN 0 AND 1 AND "
                        "tariff_rate BETWEEN 0 AND 1", name="rates_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channel.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"), nullable=False)
    purchase_cost_rate: Mapped[Decimal] = ratio_col()   # 财务BP
    first_leg_rate: Mapped[Decimal] = ratio_col()       # 物流物控：头程
    last_mile_rate: Mapped[Decimal] = ratio_col()       # 尾程
    storage_rate: Mapped[Decimal] = ratio_col()         # 仓储
    tariff_rate: Mapped[Decimal] = ratio_col()          # 关税
    updated_by: Mapped[int | None] = updated_by_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ChannelSiteRatio(Base):
    """DATA-F04-03 渠道站点比例：版本 × 月 × 渠道 × 站点（库存索赔率、其他运营费用率）。"""
    __tablename__ = "channel_site_ratio"
    __table_args__ = (
        UniqueConstraint("version_id", "month", "channel_id", "site_id", name="uq_csr_key"),
        CheckConstraint(MONTH_CHECK, name="month_first_day"),
        CheckConstraint("inventory_claim_rate BETWEEN 0 AND 1 AND other_opex_rate BETWEEN 0 AND 1",
                        name="rates_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channel.id"), nullable=False)
    site_id: Mapped[int] = mapped_column(ForeignKey("site.id"), nullable=False)
    inventory_claim_rate: Mapped[Decimal] = ratio_col()
    other_opex_rate: Mapped[Decimal] = ratio_col()
    updated_by: Mapped[int | None] = updated_by_col()
    updated_at: Mapped[datetime] = updated_at_col()


class B2bUnit(Base):
    """DATA-F04-04 B 端预算单元：版本 × 月 × 客户。"""
    __tablename__ = "b2b_unit"
    __table_args__ = (
        UniqueConstraint("version_id", "month", "customer_id", name="uq_b2b_unit_key"),
        CheckConstraint(MONTH_CHECK, name="month_first_day"),
        CheckConstraint("sales_local >= 0", name="sales_non_negative"),
        CheckConstraint("refund_rate BETWEEN 0 AND 1 AND promotion_rate BETWEEN 0 AND 1 AND "
                        "other_opex_rate BETWEEN 0 AND 1 AND commission_rate BETWEEN 0 AND 1 AND "
                        "inventory_claim_rate BETWEEN 0 AND 1 AND purchase_cost_rate BETWEEN 0 AND 1 AND "
                        "first_leg_rate BETWEEN 0 AND 1 AND last_mile_rate BETWEEN 0 AND 1 AND "
                        "storage_rate BETWEEN 0 AND 1 AND tariff_rate BETWEEN 0 AND 1", name="rates_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("b_customer.id"), nullable=False)
    # B 端业务输入
    sales_local: Mapped[Decimal] = mapped_column(Amount, nullable=False, default=Decimal(0), server_default="0")
    refund_rate: Mapped[Decimal] = ratio_col()
    promotion_rate: Mapped[Decimal] = ratio_col()
    other_opex_rate: Mapped[Decimal] = ratio_col()
    commission_rate: Mapped[Decimal] = ratio_col()        # 默认 0
    inventory_claim_rate: Mapped[Decimal] = ratio_col()   # 默认 0
    # 财务BP：采购成本占比（月 × 客户）；物流物控：四项（月 × 客户）
    purchase_cost_rate: Mapped[Decimal] = ratio_col()
    first_leg_rate: Mapped[Decimal] = ratio_col()
    last_mile_rate: Mapped[Decimal] = ratio_col()
    storage_rate: Mapped[Decimal] = ratio_col()
    tariff_rate: Mapped[Decimal] = ratio_col()
    # 派生
    revenue_cny: Mapped[Decimal | None] = amount_col()
    refund: Mapped[Decimal | None] = amount_col()
    purchase_cost: Mapped[Decimal | None] = amount_col()
    commission: Mapped[Decimal | None] = amount_col()
    promotion: Mapped[Decimal | None] = amount_col()
    first_leg: Mapped[Decimal | None] = amount_col()
    last_mile: Mapped[Decimal | None] = amount_col()
    tariff: Mapped[Decimal | None] = amount_col()
    storage: Mapped[Decimal | None] = amount_col()
    inventory_claim: Mapped[Decimal | None] = amount_col()
    other_opex: Mapped[Decimal | None] = amount_col()
    gross_profit: Mapped[Decimal | None] = amount_col()
    gross_margin: Mapped[Decimal | None] = mapped_column(Margin)
    updated_by: Mapped[int | None] = updated_by_col()
    updated_at: Mapped[datetime] = updated_at_col()


class DeptExpense(Base):
    """DATA-F05-01 部门费用预算：版本 × 月 × 部门 × 预算科目（人民币，≥ 0）。"""
    __tablename__ = "dept_expense"
    __table_args__ = (
        UniqueConstraint("version_id", "month", "department_id", "account_id", name="uq_dept_expense_key"),
        CheckConstraint(MONTH_CHECK, name="month_first_day"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("budget_account.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Amount, nullable=False, default=Decimal(0), server_default="0")
    updated_by: Mapped[int | None] = updated_by_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Reserve(Base):
    """DATA-F05-02 专项预留额度：计入该部门该科目该月预算。"""
    __tablename__ = "reserve"
    __table_args__ = (
        CheckConstraint("extract(day from plan_month) = 1", name="plan_month_first_day"),
        CheckConstraint("amount >= 0", name="amount_non_negative"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("department.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("budget_account.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    plan_month: Mapped[date] = mapped_column(Date, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = created_at_col()


class ReserveUsage(Base):
    """专项使用登记（财务BP）。"""
    __tablename__ = "reserve_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    reserve_id: Mapped[int] = mapped_column(ForeignKey("reserve.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    used_on: Mapped[date] = mapped_column(Date, nullable=False)
    voucher_no: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = created_at_col()


class CompanyOtherPl(Base):
    """DATA-F06-01 公司层其他损益：版本 × 月 × 项目（损失为负数），不分摊到任何维度。"""
    __tablename__ = "company_other_pl"
    __table_args__ = (
        UniqueConstraint("version_id", "month", "item", name="uq_company_other_pl_key"),
        CheckConstraint(MONTH_CHECK, name="month_first_day"),
        CheckConstraint(check_in("item", OtherPlItem.LABELS), name="item"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    item: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Amount, nullable=False, default=Decimal(0), server_default="0")
    updated_by: Mapped[int | None] = updated_by_col()
    updated_at: Mapped[datetime] = updated_at_col()


class SnapshotMonth(Base):
    """DATA-F08-02 快照月度汇总（冻结）：已导入实际的月份取实际。"""
    __tablename__ = "snapshot_month"
    __table_args__ = (
        UniqueConstraint("version_id", "month", name="uq_snapshot_month_key"),
        CheckConstraint(MONTH_CHECK, name="month_first_day"),
        CheckConstraint(check_in("source", ("actual", "forecast")), name="source"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("budget_version.id"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    revenue_cny: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    gross_profit: Mapped[Decimal] = mapped_column(Amount, nullable=False)
    net_profit: Mapped[Decimal] = mapped_column(Amount, nullable=False)


class ApprovalRecord(Base):
    """DATA-F07-01 审批记录。object_type = unit / task / adjustment-unit / adjustment / rule-version。"""
    __tablename__ = "approval_record"
    __table_args__ = (
        CheckConstraint(check_in("action", ("approve", "reject")), name="action"),
        CheckConstraint("action = 'approve' OR coalesce(btrim(reason), '') <> ''", name="reject_reason"),
        Index("ix_approval_record_object", "object_type", "object_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False)
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)  # dept_head / finance_head / ceo
    action: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    approver_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
