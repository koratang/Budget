"""DATA-F12-* 规则库；DATA-F11-* 预警记录与通知发件箱；DATA-F00-01 审计日志。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Metric, created_at_col
from app.models.enums import (AlertStatus, Credibility, NotifyStatus, OutboxStatus, RuleType, RuleVersionStatus,
                              check_in)


class Rule(Base):
    __tablename__ = "rule"
    __table_args__ = (CheckConstraint(check_in("type", RuleType.LABELS), name="type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("rule_version.id", use_alter=True, name="fk_rule_current_version"))
    is_preset: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = created_at_col()


class RuleVersion(Base):
    """规则版本只插入；每条规则至多一个生效版本、至多一个待审批（含待CEO审批）版本。

    content（JSONB）示例：
    预警规则 {"kind": "alert", "metric": "revenue_achievement", "comparator": "lt", "threshold": "0.70",
             "consecutive_months": 2, "applies_to": {"type": "new_channel"}, "receivers": [...]}
    阈值为小数字符串（0.70 = 70%，-0.03 = −3 个百分点）。
    新渠道放量上限 {"kind": "new_channel_ramp", "unit": "CNY/店铺/月", "limits": ["200000", ...12 项]}
    """
    __tablename__ = "rule_version"
    __table_args__ = (
        UniqueConstraint("rule_id", "version_no"),
        CheckConstraint(check_in("status", RuleVersionStatus.LABELS), name="status"),
        CheckConstraint(check_in("credibility", Credibility.LABELS), name="credibility"),
        Index("uq_rule_version_effective", "rule_id", unique=True, postgresql_where=text("status = 'effective'")),
        Index("uq_rule_version_pending", "rule_id", unique=True,
              postgresql_where=text("status IN ('pending', 'pending_ceo')")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rule.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    credibility: Mapped[str] = mapped_column(String(16), nullable=False)
    basis: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=RuleVersionStatus.PENDING)
    return_reason: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))  # 空 = 系统预置
    submitted_at: Mapped[datetime] = created_at_col()
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    """DATA-F11-01 预警记录：唯一（规则版本, 对象, 期间）。"""
    __tablename__ = "alert"
    __table_args__ = (
        UniqueConstraint("rule_version_id", "object_type", "object_id", "period", name="uq_alert_hit"),
        CheckConstraint(check_in("status", AlertStatus.LABELS), name="status"),
        CheckConstraint(check_in("notify_status", NotifyStatus.LABELS), name="notify_status"),
        CheckConstraint("extract(day from period) = 1", name="period_first_day"),
        CheckConstraint("status = 'open' OR coalesce(btrim(resolve_note), '') <> ''", name="resolve_note"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_version_id: Mapped[int] = mapped_column(ForeignKey("rule_version.id"), nullable=False)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False)  # store / channel / department / category …
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    object_name: Mapped[str] = mapped_column(String(128), nullable=False)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    metric_value: Mapped[Decimal | None] = mapped_column(Metric)
    threshold: Mapped[Decimal | None] = mapped_column(Metric)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=AlertStatus.OPEN)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolve_note: Mapped[str | None] = mapped_column(Text)
    notify_status: Mapped[str] = mapped_column(String(16), nullable=False, default=NotifyStatus.PENDING)
    updated_after_resolve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                        server_default="false")
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))  # 触发评估的导入
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NotificationOutbox(Base):
    """DATA-F11-02 通知发件箱：模板参数不含金额（NFR-005）；首发 + 每 5 分钟重试最多 3 次（DEC-011）。"""
    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint(check_in("status", (OutboxStatus.PENDING, OutboxStatus.SENT, OutboxStatus.FAILED)),
                        name="status"),
        Index("ix_notification_outbox_due", "status", "next_attempt_at"),
        Index("ix_notification_outbox_biz", "biz_type", "biz_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    biz_type: Mapped[str] = mapped_column(String(24), nullable=False)  # alert / task_published / overdue / …
    biz_id: Mapped[int | None] = mapped_column(Integer)
    receivers: Mapped[list] = mapped_column(JSONB, nullable=False)  # 钉钉 userid 列表
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)     # {title, name, object, period, link}
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OutboxStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    attempt_log: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    dingtalk_task_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_col()
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """DATA-F00-01 审计日志：只追加；触发器禁止 UPDATE/DELETE/TRUNCATE，应用账号回收 UPDATE/DELETE 权限。"""
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_object", "object_type", "object_id"),
                      Index("ix_audit_log_occurred_at", "occurred_at"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_id: Mapped[int | None] = mapped_column(Integer)  # 不设外键：审计行独立于用户表
    actor_userid: Mapped[str | None] = mapped_column(String(64))
    actor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | list | None] = mapped_column(JSONB)
    after: Mapped[dict | list | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    auth_source: Mapped[str | None] = mapped_column(String(16))
