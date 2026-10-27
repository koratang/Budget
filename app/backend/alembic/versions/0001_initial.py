"""0001 初始迁移：建全部 DATA-* 表；锁定版本 / 锁定汇率 / 审计只追加触发器；预置 8 个角色与 3 条待审批预警规则（AC-F12-03）。

Revision ID: 0001
Revises: 
Create Date: 2026-10-27 10:20:28.711510
"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# 数据库层兜底约束（服务层之外的第二道防线）
# ---------------------------------------------------------------------------
# DEC-016：锁定版本（locked = true）下的预算数据行禁止新增、修改、删除
LOCKED_DATA_TABLES = ("platform_unit", "channel_category_ratio", "channel_site_ratio", "b2b_unit",
                      "dept_expense", "company_other_pl", "reserve")

TRIGGER_SQL = [
    """
    CREATE FUNCTION budget_reject_locked_version_rows() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP IN ('UPDATE', 'DELETE') AND EXISTS (
            SELECT 1 FROM budget_version WHERE id = OLD.version_id AND locked) THEN
            RAISE EXCEPTION '版本已锁定，不能修改' USING ERRCODE = 'BG001';
        END IF;
        IF TG_OP IN ('INSERT', 'UPDATE') AND TG_ARGV[0] = 'all' AND EXISTS (
            SELECT 1 FROM budget_version WHERE id = NEW.version_id AND locked) THEN
            RAISE EXCEPTION '版本已锁定，不能修改' USING ERRCODE = 'BG001';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END $$;
    """,
    *[
        f"CREATE TRIGGER trg_{t}_locked BEFORE INSERT OR UPDATE OR DELETE ON {t} "
        f"FOR EACH ROW EXECUTE FUNCTION budget_reject_locked_version_rows('all')"
        for t in LOCKED_DATA_TABLES
    ],
    # 快照月度汇总：发布（锁定）后仍可写入冻结汇总，但不可改删
    "CREATE TRIGGER trg_snapshot_month_locked BEFORE UPDATE OR DELETE ON snapshot_month "
    "FOR EACH ROW EXECUTE FUNCTION budget_reject_locked_version_rows('update_delete')",
    # 已锁定版本本身不可修改、不可删除
    """
    CREATE FUNCTION budget_reject_locked_version() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF OLD.locked THEN
            RAISE EXCEPTION '版本已锁定，不能修改' USING ERRCODE = 'BG001';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END $$;
    """,
    "CREATE TRIGGER trg_budget_version_locked BEFORE UPDATE OR DELETE ON budget_version "
    "FOR EACH ROW EXECUTE FUNCTION budget_reject_locked_version()",
    # DEC-020：年度存在年初原始目标即锁定预算汇率；已有币种禁止改删，尚无汇率的币种允许新增
    """
    CREATE FUNCTION budget_reject_locked_fx() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF EXISTS (SELECT 1 FROM budget_version
                   WHERE type = 'original_target'
                     AND year IN (OLD.year, CASE WHEN TG_OP = 'UPDATE' THEN NEW.year ELSE OLD.year END)) THEN
            RAISE EXCEPTION '已随年初原始目标锁定' USING ERRCODE = 'BG002';
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END $$;
    """,
    "CREATE TRIGGER trg_fx_budget_locked BEFORE UPDATE OR DELETE ON fx_budget "
    "FOR EACH ROW EXECUTE FUNCTION budget_reject_locked_fx()",
    # DEC-010 / NFR-004：审计表只追加
    """
    CREATE FUNCTION budget_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION '审计日志只允许追加，不能修改或删除' USING ERRCODE = 'BG003';
    END $$;
    """,
    "CREATE TRIGGER trg_audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log "
    "FOR EACH ROW EXECUTE FUNCTION budget_audit_append_only()",
    "CREATE TRIGGER trg_audit_log_no_truncate BEFORE TRUNCATE ON audit_log "
    "FOR EACH STATEMENT EXECUTE FUNCTION budget_audit_append_only()",
    "REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM PUBLIC",
    "REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM CURRENT_USER",
]

DROP_TRIGGER_SQL = [
    "DROP FUNCTION IF EXISTS budget_reject_locked_version_rows() CASCADE",
    "DROP FUNCTION IF EXISTS budget_reject_locked_version() CASCADE",
    "DROP FUNCTION IF EXISTS budget_reject_locked_fx() CASCADE",
    "DROP FUNCTION IF EXISTS budget_audit_append_only() CASCADE",
]

ROLES = [
    ("ceo", "CEO", 1), ("finance_head", "财务负责人", 2), ("finance_bp", "财务BP", 3), ("operations", "运营", 4),
    ("b2b", "B端业务", 5), ("logistics", "物流物控", 6), ("dept_head", "部门负责人", 7),
    ("dept_budget", "部门预算专员", 8),
]

# AC-F12-03：首次部署预置三条「未验证经验」的待审批预警规则；阈值为小数字符串
PRESET_ALERT_RULES = [
    ("新渠道连续 2 个月收入达成率低于 70%",
     {"kind": "alert", "metric": "revenue_achievement", "comparator": "lt", "threshold": "0.70",
      "consecutive_months": 2, "applies_to": {"type": "new_channel"},
      "receivers": ["dept_head", "operations", "finance_head"]}),
    ("部门费用额度使用率超出时间进度 10 个百分点以上",
     {"kind": "alert", "metric": "usage_minus_time_progress", "comparator": "gte", "threshold": "0.10",
      "consecutive_months": 1, "applies_to": {"type": "department"},
      "receivers": ["dept_head", "finance_head", "ceo"]}),
    ("品类毛利率比预算低 3 个百分点以上",
     {"kind": "alert", "metric": "gross_margin_diff", "comparator": "lte", "threshold": "-0.03",
      "consecutive_months": 1, "applies_to": {"type": "category"},
      "receivers": ["finance_head", "operations"]}),
]


def _seed_roles() -> None:
    role = sa.table("role", sa.column("code", sa.String), sa.column("name", sa.String),
                    sa.column("sort", sa.Integer))
    op.bulk_insert(role, [{"code": c, "name": n, "sort": o} for c, n, o in ROLES])


def _seed_preset_rules() -> None:
    conn = op.get_bind()
    for name, content in PRESET_ALERT_RULES:
        rule_id = conn.execute(
            sa.text("INSERT INTO rule (name, type, is_preset) VALUES (:n, 'alert_rule', true) RETURNING id"),
            {"n": name}).scalar_one()
        conn.execute(
            sa.text("INSERT INTO rule_version (rule_id, version_no, content, credibility, basis, status) "
                    "VALUES (:r, 1, CAST(:c AS jsonb), 'unverified', :b, 'pending')"),
            {"r": rule_id, "c": json.dumps(content, ensure_ascii=False),
             "b": "上一轮预算经验（系统预置，待审批验证）"})


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_userid', sa.String(length=64), nullable=True),
    sa.Column('actor_name', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('object_type', sa.String(length=32), nullable=False),
    sa.Column('object_id', sa.String(length=64), nullable=True),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('auth_source', sa.String(length=16), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index('ix_audit_log_object', 'audit_log', ['object_type', 'object_id'], unique=False)
    op.create_index('ix_audit_log_occurred_at', 'audit_log', ['occurred_at'], unique=False)
    op.create_table('budget_account',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('is_dept_expense', sa.Boolean(), nullable=False),
    sa.Column('pl_item', sa.String(length=32), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('sort', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_budget_account')),
    sa.UniqueConstraint('name', name=op.f('uq_budget_account_name'))
    )
    op.create_table('category',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('sort', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_category')),
    sa.UniqueConstraint('name', name=op.f('uq_category_name'))
    )
    op.create_table('channel',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('is_new_channel', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('new_channel_start', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('sort', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint('new_channel_start IS NULL OR extract(day from new_channel_start) = 1', name=op.f('ck_channel_start_first_day')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_channel')),
    sa.UniqueConstraint('name', name=op.f('uq_channel_name'))
    )
    op.create_table('department',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('head_user_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('sort', sa.Integer(), server_default='0', nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_department')),
    sa.UniqueConstraint('name', name=op.f('uq_department_name'))
    )
    op.create_table('notification_outbox',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('biz_type', sa.String(length=24), nullable=False),
    sa.Column('biz_id', sa.Integer(), nullable=True),
    sa.Column('receivers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('attempt_log', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('dingtalk_task_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name=op.f('ck_notification_outbox_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_outbox'))
    )
    op.create_index('ix_notification_outbox_biz', 'notification_outbox', ['biz_type', 'biz_id'], unique=False)
    op.create_index('ix_notification_outbox_due', 'notification_outbox', ['status', 'next_attempt_at'], unique=False)
    op.create_table('role',
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_role')),
    sa.UniqueConstraint('name', name=op.f('uq_role_name'))
    )
    op.create_table('site',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=8), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_site')),
    sa.UniqueConstraint('code', name=op.f('uq_site_code')),
    sa.UniqueConstraint('name', name=op.f('uq_site_name'))
    )
    op.create_table('app_user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dingtalk_userid', sa.String(length=64), nullable=False),
    sa.Column('union_id', sa.String(length=64), nullable=True),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('dingtalk_dept', sa.String(length=128), nullable=True),
    sa.Column('department_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_app_user_department_id_department')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_app_user')),
    sa.UniqueConstraint('dingtalk_userid', name=op.f('uq_app_user_dingtalk_userid'))
    )
    op.create_table('b_customer',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_b_customer_department_id_department')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_b_customer')),
    sa.UniqueConstraint('name', name=op.f('uq_b_customer_name'))
    )
    op.create_index(op.f('ix_b_customer_department_id'), 'b_customer', ['department_id'], unique=False)
    op.create_table('spu',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('first_listed_on', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['category.id'], name=op.f('fk_spu_category_id_category')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_spu')),
    sa.UniqueConstraint('code', name=op.f('uq_spu_code'))
    )
    op.create_index(op.f('ix_spu_category_id'), 'spu', ['category_id'], unique=False)
    op.create_table('store',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('channel_id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('is_new_channel', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('new_channel_start', sa.Date(), nullable=True),
    sa.CheckConstraint('new_channel_start IS NULL OR extract(day from new_channel_start) = 1', name=op.f('ck_store_start_first_day')),
    sa.ForeignKeyConstraint(['channel_id'], ['channel.id'], name=op.f('fk_store_channel_id_channel')),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_store_site_id_site')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_store')),
    sa.UniqueConstraint('id', 'channel_id', name='uq_store_id_channel'),
    sa.UniqueConstraint('id', 'site_id', name='uq_store_id_site'),
    sa.UniqueConstraint('name', name=op.f('uq_store_name'))
    )
    op.create_index(op.f('ix_store_channel_id'), 'store', ['channel_id'], unique=False)
    op.create_table('approval_record',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('object_type', sa.String(length=24), nullable=False),
    sa.Column('object_id', sa.Integer(), nullable=False),
    sa.Column('level', sa.String(length=16), nullable=False),
    sa.Column('action', sa.String(length=8), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('approver_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("action = 'approve' OR coalesce(btrim(reason), '') <> ''", name=op.f('ck_approval_record_reject_reason')),
    sa.CheckConstraint("action IN ('approve', 'reject')", name=op.f('ck_approval_record_action')),
    sa.ForeignKeyConstraint(['approver_id'], ['app_user.id'], name=op.f('fk_approval_record_approver_id_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_record'))
    )
    op.create_index('ix_approval_record_object', 'approval_record', ['object_type', 'object_id'], unique=False)
    op.create_table('budget_version',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=24), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('quarter', sa.SmallInteger(), nullable=True),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('adjust_reason', sa.Text(), nullable=True),
    sa.Column('locked', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('published_on', sa.Date(), nullable=True),
    sa.Column('source_version_id', sa.Integer(), nullable=True),
    sa.Column('approved_by', sa.Integer(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("type IN ('draft', 'original_target', 'adjustment_draft', 'adjusted_target', 'rolling_draft', 'snapshot')", name=op.f('ck_budget_version_type')),
    sa.CheckConstraint('quarter IS NULL OR quarter BETWEEN 1 AND 4', name=op.f('ck_budget_version_quarter')),
    sa.ForeignKeyConstraint(['approved_by'], ['app_user.id'], name=op.f('fk_budget_version_approved_by_app_user')),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_budget_version_created_by_app_user')),
    sa.ForeignKeyConstraint(['source_version_id'], ['budget_version.id'], name=op.f('fk_budget_version_source_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_budget_version')),
    sa.UniqueConstraint('year', 'type', 'version_no', name=op.f('uq_budget_version_year_type_version_no'))
    )
    op.create_index('uq_budget_version_rolling_quarter', 'budget_version', ['year', 'quarter'], unique=True, postgresql_where=sa.text("type IN ('rolling_draft', 'snapshot')"))
    op.create_table('fx_actual',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('rate', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_fx_actual_month_first_day')),
    sa.CheckConstraint('rate = round(rate, 4)', name=op.f('ck_fx_actual_rate_4dp')),
    sa.CheckConstraint('rate > 0', name=op.f('ck_fx_actual_rate_positive')),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_fx_actual_updated_by_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fx_actual')),
    sa.UniqueConstraint('month', 'currency', name=op.f('uq_fx_actual_month_currency'))
    )
    op.create_table('fx_budget',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('rate', sa.Numeric(precision=12, scale=6), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('rate > 0', name=op.f('ck_fx_budget_rate_positive')),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_fx_budget_updated_by_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_fx_budget')),
    sa.UniqueConstraint('year', 'currency', name=op.f('uq_fx_budget_year_currency'))
    )
    op.create_table('kingdee_account_map',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kingdee_code', sa.String(length=32), nullable=False),
    sa.Column('kingdee_name', sa.String(length=128), nullable=True),
    sa.Column('account_id', sa.Integer(), nullable=True),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['budget_account.id'], name=op.f('fk_kingdee_account_map_account_id_budget_account')),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_kingdee_account_map_updated_by_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kingdee_account_map')),
    sa.UniqueConstraint('kingdee_code', name=op.f('uq_kingdee_account_map_kingdee_code'))
    )
    op.create_table('rule',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('type', sa.String(length=24), nullable=False),
    sa.Column('current_version_id', sa.Integer(), nullable=True),
    sa.Column('is_preset', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("type IN ('driver_assumption', 'alert_rule', 'quota_standard')", name=op.f('ck_rule_type')),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_rule_created_by_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rule'))
    )
    op.create_table('sku',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('spu_id', sa.Integer(), nullable=False),
    sa.Column('listed_on', sa.Date(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['spu_id'], ['spu.id'], name=op.f('fk_sku_spu_id_spu')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sku')),
    sa.UniqueConstraint('code', name=op.f('uq_sku_code'))
    )
    op.create_index(op.f('ix_sku_spu_id'), 'sku', ['spu_id'], unique=False)
    op.create_table('user_role',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role_code', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['role_code'], ['role.code'], name=op.f('fk_user_role_role_code_role')),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_role_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_code', name=op.f('pk_user_role'))
    )
    op.create_table('user_scope',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('scope_type', sa.String(length=16), nullable=False),
    sa.Column('object_id', sa.Integer(), nullable=False),
    sa.CheckConstraint("scope_type IN ('department', 'channel', 'store', 'customer')", name=op.f('ck_user_scope_scope_type')),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_scope_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_scope')),
    sa.UniqueConstraint('user_id', 'scope_type', 'object_id', name=op.f('uq_user_scope_user_id_scope_type_object_id'))
    )
    op.create_index(op.f('ix_user_scope_user_id'), 'user_scope', ['user_id'], unique=False)
    op.create_table('user_session',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('auth_source', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_active_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("auth_source IN ('dingtalk', 'dev')", name=op.f('ck_user_session_auth_source')),
    sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], name=op.f('fk_user_session_user_id_app_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_session')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_user_session_token_hash'))
    )
    op.create_index(op.f('ix_user_session_user_id'), 'user_session', ['user_id'], unique=False)
    op.create_table('variance_note',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('report_type', sa.String(length=24), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('object_type', sa.String(length=24), nullable=False),
    sa.Column('object_key', sa.String(length=128), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_variance_note_month_first_day')),
    sa.ForeignKeyConstraint(['author_id'], ['app_user.id'], name=op.f('fk_variance_note_author_id_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_variance_note')),
    sa.UniqueConstraint('report_type', 'month', 'object_type', 'object_key', name='uq_variance_note_key')
    )
    op.create_table('b2b_unit',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('customer_id', sa.Integer(), nullable=False),
    sa.Column('sales_local', sa.Numeric(precision=20, scale=6), server_default='0', nullable=False),
    sa.Column('refund_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('promotion_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('other_opex_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('commission_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('inventory_claim_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('purchase_cost_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('first_leg_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('last_mile_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('storage_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('tariff_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('revenue_cny', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('refund', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('purchase_cost', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('commission', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('promotion', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('first_leg', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('last_mile', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('tariff', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('storage', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('inventory_claim', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('other_opex', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('gross_profit', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('gross_margin', sa.Numeric(precision=12, scale=8), nullable=True),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_b2b_unit_month_first_day')),
    sa.CheckConstraint('refund_rate BETWEEN 0 AND 1 AND promotion_rate BETWEEN 0 AND 1 AND other_opex_rate BETWEEN 0 AND 1 AND commission_rate BETWEEN 0 AND 1 AND inventory_claim_rate BETWEEN 0 AND 1 AND purchase_cost_rate BETWEEN 0 AND 1 AND first_leg_rate BETWEEN 0 AND 1 AND last_mile_rate BETWEEN 0 AND 1 AND storage_rate BETWEEN 0 AND 1 AND tariff_rate BETWEEN 0 AND 1', name=op.f('ck_b2b_unit_rates_range')),
    sa.CheckConstraint('sales_local >= 0', name=op.f('ck_b2b_unit_sales_non_negative')),
    sa.ForeignKeyConstraint(['customer_id'], ['b_customer.id'], name=op.f('fk_b2b_unit_customer_id_b_customer')),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_b2b_unit_updated_by_app_user')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_b2b_unit_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_b2b_unit')),
    sa.UniqueConstraint('version_id', 'month', 'customer_id', name='uq_b2b_unit_key')
    )
    op.create_table('budget_task',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('deadline', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('ceo_return_reason', sa.Text(), nullable=True),
    sa.Column('overdue_notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('in_progress', 'pending_ceo', 'completed')", name=op.f('ck_budget_task_status')),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_budget_task_created_by_app_user')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_budget_task_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_budget_task'))
    )
    op.create_index('uq_budget_task_open_year', 'budget_task', ['year'], unique=True, postgresql_where=sa.text("status IN ('in_progress', 'pending_ceo')"))
    op.create_table('channel_category_ratio',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('channel_id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('purchase_cost_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('first_leg_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('last_mile_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('storage_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('tariff_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_channel_category_ratio_month_first_day')),
    sa.CheckConstraint('purchase_cost_rate BETWEEN 0 AND 1 AND first_leg_rate BETWEEN 0 AND 1 AND last_mile_rate BETWEEN 0 AND 1 AND storage_rate BETWEEN 0 AND 1 AND tariff_rate BETWEEN 0 AND 1', name=op.f('ck_channel_category_ratio_rates_range')),
    sa.ForeignKeyConstraint(['category_id'], ['category.id'], name=op.f('fk_channel_category_ratio_category_id_category')),
    sa.ForeignKeyConstraint(['channel_id'], ['channel.id'], name=op.f('fk_channel_category_ratio_channel_id_channel')),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_channel_category_ratio_site_id_site')),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_channel_category_ratio_updated_by_app_user')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_channel_category_ratio_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_channel_category_ratio')),
    sa.UniqueConstraint('version_id', 'month', 'channel_id', 'site_id', 'category_id', name='uq_ccr_key')
    )
    op.create_table('channel_site_ratio',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('channel_id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('inventory_claim_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('other_opex_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_channel_site_ratio_month_first_day')),
    sa.CheckConstraint('inventory_claim_rate BETWEEN 0 AND 1 AND other_opex_rate BETWEEN 0 AND 1', name=op.f('ck_channel_site_ratio_rates_range')),
    sa.ForeignKeyConstraint(['channel_id'], ['channel.id'], name=op.f('fk_channel_site_ratio_channel_id_channel')),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_channel_site_ratio_site_id_site')),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_channel_site_ratio_updated_by_app_user')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_channel_site_ratio_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_channel_site_ratio')),
    sa.UniqueConstraint('version_id', 'month', 'channel_id', 'site_id', name='uq_csr_key')
    )
    op.create_table('company_other_pl',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('item', sa.String(length=16), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=6), server_default='0', nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("item IN ('finance_cost', 'fx_gain_loss', 'non_operating', 'income_tax')", name=op.f('ck_company_other_pl_item')),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_company_other_pl_month_first_day')),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_company_other_pl_updated_by_app_user')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_company_other_pl_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_company_other_pl')),
    sa.UniqueConstraint('version_id', 'month', 'item', name='uq_company_other_pl_key')
    )
    op.create_table('dept_expense',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=6), server_default='0', nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount >= 0', name=op.f('ck_dept_expense_amount_non_negative')),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_dept_expense_month_first_day')),
    sa.ForeignKeyConstraint(['account_id'], ['budget_account.id'], name=op.f('fk_dept_expense_account_id_budget_account')),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_dept_expense_department_id_department')),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_dept_expense_updated_by_app_user')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_dept_expense_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dept_expense')),
    sa.UniqueConstraint('version_id', 'month', 'department_id', 'account_id', name='uq_dept_expense_key')
    )
    op.create_table('platform_unit',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('channel_id', sa.Integer(), nullable=False),
    sa.Column('store_id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('is_new', sa.Boolean(), nullable=False),
    sa.Column('spu_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('avg_sales', sa.Numeric(precision=18, scale=4), server_default='0', nullable=False),
    sa.Column('avg_price', sa.Numeric(precision=18, scale=4), server_default='0', nullable=False),
    sa.Column('discount_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('refund_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('ad_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('commission_rate', sa.Numeric(precision=9, scale=6), server_default='0', nullable=False),
    sa.Column('sales_qty', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('revenue_local', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('revenue_cny', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('refund', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('purchase_cost', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('commission', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('promotion', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('first_leg', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('last_mile', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('tariff', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('storage', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('inventory_claim', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('other_opex', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('gross_profit', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('gross_margin', sa.Numeric(precision=12, scale=8), nullable=True),
    sa.Column('over_limit', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('over_limit_reason', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('discount_rate BETWEEN 0 AND 1 AND refund_rate BETWEEN 0 AND 1 AND ad_rate BETWEEN 0 AND 1 AND commission_rate BETWEEN 0 AND 1', name=op.f('ck_platform_unit_rates_range')),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_platform_unit_month_first_day')),
    sa.CheckConstraint('spu_count >= 0 AND avg_sales >= 0 AND avg_price >= 0', name=op.f('ck_platform_unit_drivers_non_negative')),
    sa.ForeignKeyConstraint(['category_id'], ['category.id'], name=op.f('fk_platform_unit_category_id_category')),
    sa.ForeignKeyConstraint(['channel_id'], ['channel.id'], name=op.f('fk_platform_unit_channel_id_channel')),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_platform_unit_site_id_site')),
    sa.ForeignKeyConstraint(['store_id', 'channel_id'], ['store.id', 'store.channel_id'], name='fk_platform_unit_store_channel'),
    sa.ForeignKeyConstraint(['store_id', 'site_id'], ['store.id', 'store.site_id'], name='fk_platform_unit_store_site'),
    sa.ForeignKeyConstraint(['store_id'], ['store.id'], name=op.f('fk_platform_unit_store_id_store')),
    sa.ForeignKeyConstraint(['updated_by'], ['app_user.id'], name=op.f('fk_platform_unit_updated_by_app_user')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_platform_unit_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_platform_unit')),
    sa.UniqueConstraint('version_id', 'month', 'channel_id', 'store_id', 'site_id', 'category_id', 'is_new', name='uq_platform_unit_key')
    )
    op.create_index('ix_platform_unit_version_store_month', 'platform_unit', ['version_id', 'store_id', 'month'], unique=False)
    op.create_table('reserve',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('plan_month', sa.Date(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount >= 0', name=op.f('ck_reserve_amount_non_negative')),
    sa.CheckConstraint('extract(day from plan_month) = 1', name=op.f('ck_reserve_plan_month_first_day')),
    sa.ForeignKeyConstraint(['account_id'], ['budget_account.id'], name=op.f('fk_reserve_account_id_budget_account')),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_reserve_created_by_app_user')),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_reserve_department_id_department')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_reserve_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reserve'))
    )
    op.create_index(op.f('ix_reserve_version_id'), 'reserve', ['version_id'], unique=False)
    op.create_table('rule_version',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rule_id', sa.Integer(), nullable=False),
    sa.Column('version_no', sa.Integer(), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('credibility', sa.String(length=16), nullable=False),
    sa.Column('basis', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('return_reason', sa.Text(), nullable=True),
    sa.Column('submitted_by', sa.Integer(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('approved_by', sa.Integer(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('effective_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("credibility IN ('unverified', 'observed', 'verified')", name=op.f('ck_rule_version_credibility')),
    sa.CheckConstraint("status IN ('pending', 'pending_ceo', 'effective', 'history', 'returned')", name=op.f('ck_rule_version_status')),
    sa.ForeignKeyConstraint(['approved_by'], ['app_user.id'], name=op.f('fk_rule_version_approved_by_app_user')),
    sa.ForeignKeyConstraint(['rule_id'], ['rule.id'], name=op.f('fk_rule_version_rule_id_rule')),
    sa.ForeignKeyConstraint(['submitted_by'], ['app_user.id'], name=op.f('fk_rule_version_submitted_by_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rule_version')),
    sa.UniqueConstraint('rule_id', 'version_no', name=op.f('uq_rule_version_rule_id_version_no'))
    )
    op.create_index('uq_rule_version_effective', 'rule_version', ['rule_id'], unique=True, postgresql_where=sa.text("status = 'effective'"))
    op.create_index('uq_rule_version_pending', 'rule_version', ['rule_id'], unique=True, postgresql_where=sa.text("status IN ('pending', 'pending_ceo')"))
    op.create_table('snapshot_month',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('source', sa.String(length=8), nullable=False),
    sa.Column('revenue_cny', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('gross_profit', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('net_profit', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.CheckConstraint("source IN ('actual', 'forecast')", name=op.f('ck_snapshot_month_source')),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_snapshot_month_month_first_day')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_snapshot_month_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_snapshot_month')),
    sa.UniqueConstraint('version_id', 'month', name='uq_snapshot_month_key')
    )
    op.create_table('target_adjustment',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('quarter', sa.SmallInteger(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('draft_version_id', sa.Integer(), nullable=False),
    sa.Column('result_version_id', sa.Integer(), nullable=True),
    sa.Column('initiated_by', sa.Integer(), nullable=True),
    sa.Column('ceo_return_reason', sa.Text(), nullable=True),
    sa.Column('effective_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('in_progress', 'pending_ceo', 'effective')", name=op.f('ck_target_adjustment_status')),
    sa.CheckConstraint('quarter BETWEEN 1 AND 4', name=op.f('ck_target_adjustment_quarter')),
    sa.ForeignKeyConstraint(['draft_version_id'], ['budget_version.id'], name=op.f('fk_target_adjustment_draft_version_id_budget_version')),
    sa.ForeignKeyConstraint(['initiated_by'], ['app_user.id'], name=op.f('fk_target_adjustment_initiated_by_app_user')),
    sa.ForeignKeyConstraint(['result_version_id'], ['budget_version.id'], name=op.f('fk_target_adjustment_result_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_target_adjustment'))
    )
    op.create_index('uq_target_adjustment_effective_quarter', 'target_adjustment', ['year', 'quarter'], unique=True, postgresql_where=sa.text("status = 'effective'"))
    op.create_index('uq_target_adjustment_open_year', 'target_adjustment', ['year'], unique=True, postgresql_where=sa.text("status IN ('in_progress', 'pending_ceo')"))
    op.create_table('filling_unit',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=True),
    sa.Column('adjustment_id', sa.Integer(), nullable=True),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('unit_type', sa.String(length=16), nullable=False),
    sa.Column('scope_object_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('filler_id', sa.Integer(), nullable=False),
    sa.Column('reviewer_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('return_reason', sa.Text(), nullable=True),
    sa.Column('adjust_reason', sa.Text(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('not_started', 'filling', 'adjusting', 'submitted', 'dept_approved', 'approved', 'returned')", name=op.f('ck_filling_unit_status')),
    sa.CheckConstraint("unit_type IN ('platform', 'b2b', 'cost_ratio', 'logistics_ratio', 'dept_expense')", name=op.f('ck_filling_unit_unit_type')),
    sa.CheckConstraint('(task_id IS NULL) <> (adjustment_id IS NULL)', name=op.f('ck_filling_unit_task_xor_adjustment')),
    sa.ForeignKeyConstraint(['adjustment_id'], ['target_adjustment.id'], name=op.f('fk_filling_unit_adjustment_id_target_adjustment')),
    sa.ForeignKeyConstraint(['filler_id'], ['app_user.id'], name=op.f('fk_filling_unit_filler_id_app_user')),
    sa.ForeignKeyConstraint(['reviewer_id'], ['app_user.id'], name=op.f('fk_filling_unit_reviewer_id_app_user')),
    sa.ForeignKeyConstraint(['task_id'], ['budget_task.id'], name=op.f('fk_filling_unit_task_id_budget_task')),
    sa.ForeignKeyConstraint(['version_id'], ['budget_version.id'], name=op.f('fk_filling_unit_version_id_budget_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_filling_unit')),
    sa.UniqueConstraint('adjustment_id', 'unit_type', 'scope_object_id', name='uq_filling_unit_adjustment_scope', postgresql_nulls_not_distinct=True),
    sa.UniqueConstraint('task_id', 'unit_type', 'scope_object_id', name='uq_filling_unit_task_scope', postgresql_nulls_not_distinct=True)
    )
    op.create_index(op.f('ix_filling_unit_adjustment_id'), 'filling_unit', ['adjustment_id'], unique=False)
    op.create_index(op.f('ix_filling_unit_filler_id'), 'filling_unit', ['filler_id'], unique=False)
    op.create_index(op.f('ix_filling_unit_reviewer_id'), 'filling_unit', ['reviewer_id'], unique=False)
    op.create_index(op.f('ix_filling_unit_task_id'), 'filling_unit', ['task_id'], unique=False)
    op.create_table('reserve_usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('reserve_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('used_on', sa.Date(), nullable=False),
    sa.Column('voucher_no', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], name=op.f('fk_reserve_usage_created_by_app_user')),
    sa.ForeignKeyConstraint(['reserve_id'], ['reserve.id'], name=op.f('fk_reserve_usage_reserve_id_reserve')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reserve_usage'))
    )
    op.create_index(op.f('ix_reserve_usage_reserve_id'), 'reserve_usage', ['reserve_id'], unique=False)
    op.create_table('import_batch',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('period', sa.Date(), nullable=True),
    sa.Column('parent_batch_id', sa.Integer(), nullable=True),
    sa.Column('file_path', sa.String(length=512), nullable=True),
    sa.Column('file_name', sa.String(length=256), nullable=False),
    sa.Column('file_size', sa.BigInteger(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('errors', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('replaced_by_batch_id', sa.Integer(), nullable=True),
    sa.Column('unit_id', sa.Integer(), nullable=True),
    sa.Column('uploaded_by', sa.Integer(), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('confirmed_by', sa.Integer(), nullable=True),
    sa.CheckConstraint("source IN ('kingdee', 'kingdee-history', 'bi', 'sku', 'template')", name=op.f('ck_import_batch_source')),
    sa.CheckConstraint("status IN ('validating', 'validation_failed', 'pending_confirm', 'effective', 'replaced', 'discarded', 'interrupted')", name=op.f('ck_import_batch_status')),
    sa.CheckConstraint('period IS NULL OR extract(day from period) = 1', name=op.f('ck_import_batch_period_first_day')),
    sa.ForeignKeyConstraint(['confirmed_by'], ['app_user.id'], name=op.f('fk_import_batch_confirmed_by_app_user')),
    sa.ForeignKeyConstraint(['parent_batch_id'], ['import_batch.id'], name=op.f('fk_import_batch_parent_batch_id_import_batch')),
    sa.ForeignKeyConstraint(['replaced_by_batch_id'], ['import_batch.id'], name=op.f('fk_import_batch_replaced_by_batch_id_import_batch')),
    sa.ForeignKeyConstraint(['unit_id'], ['filling_unit.id'], name=op.f('fk_import_batch_unit_id_filling_unit')),
    sa.ForeignKeyConstraint(['uploaded_by'], ['app_user.id'], name=op.f('fk_import_batch_uploaded_by_app_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_batch'))
    )
    op.create_index('ix_import_batch_source_period_status', 'import_batch', ['source', 'period', 'status'], unique=False)
    op.create_table('alert',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('rule_version_id', sa.Integer(), nullable=False),
    sa.Column('object_type', sa.String(length=24), nullable=False),
    sa.Column('object_id', sa.String(length=64), nullable=False),
    sa.Column('object_name', sa.String(length=128), nullable=False),
    sa.Column('period', sa.Date(), nullable=False),
    sa.Column('metric_value', sa.Numeric(precision=20, scale=8), nullable=True),
    sa.Column('threshold', sa.Numeric(precision=20, scale=8), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('resolved_by', sa.Integer(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolve_note', sa.Text(), nullable=True),
    sa.Column('notify_status', sa.String(length=16), nullable=False),
    sa.Column('updated_after_resolve', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("notify_status IN ('pending', 'sent', 'retrying', 'failed')", name=op.f('ck_alert_notify_status')),
    sa.CheckConstraint("status = 'open' OR coalesce(btrim(resolve_note), '') <> ''", name=op.f('ck_alert_resolve_note')),
    sa.CheckConstraint("status IN ('open', 'resolved')", name=op.f('ck_alert_status')),
    sa.CheckConstraint('extract(day from period) = 1', name=op.f('ck_alert_period_first_day')),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batch.id'], name=op.f('fk_alert_import_batch_id_import_batch')),
    sa.ForeignKeyConstraint(['resolved_by'], ['app_user.id'], name=op.f('fk_alert_resolved_by_app_user')),
    sa.ForeignKeyConstraint(['rule_version_id'], ['rule_version.id'], name=op.f('fk_alert_rule_version_id_rule_version')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert')),
    sa.UniqueConstraint('rule_version_id', 'object_type', 'object_id', 'period', name='uq_alert_hit')
    )
    op.create_table('bi_actual_agg',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('store_id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.Column('is_new', sa.Boolean(), nullable=False),
    sa.Column('spu_count', sa.Integer(), nullable=False),
    sa.Column('qty', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('revenue_local', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('revenue_cny', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_bi_actual_agg_month_first_day')),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batch.id'], name=op.f('fk_bi_actual_agg_batch_id_import_batch')),
    sa.ForeignKeyConstraint(['category_id'], ['category.id'], name=op.f('fk_bi_actual_agg_category_id_category')),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_bi_actual_agg_site_id_site')),
    sa.ForeignKeyConstraint(['store_id'], ['store.id'], name=op.f('fk_bi_actual_agg_store_id_store')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bi_actual_agg')),
    sa.UniqueConstraint('batch_id', 'month', 'store_id', 'site_id', 'category_id', 'is_new', name='uq_bi_agg_key')
    )
    op.create_index('ix_bi_actual_agg_month_store', 'bi_actual_agg', ['month', 'store_id'], unique=False)
    op.create_table('bi_actual_sku',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('row_no', sa.Integer(), nullable=True),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('store_id', sa.Integer(), nullable=False),
    sa.Column('site_id', sa.Integer(), nullable=False),
    sa.Column('sku_id', sa.Integer(), nullable=False),
    sa.Column('qty', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('sales_local', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('ad_fee', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.Column('platform_fee', sa.Numeric(precision=20, scale=6), nullable=True),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_bi_actual_sku_month_first_day')),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batch.id'], name=op.f('fk_bi_actual_sku_batch_id_import_batch')),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_bi_actual_sku_site_id_site')),
    sa.ForeignKeyConstraint(['sku_id'], ['sku.id'], name=op.f('fk_bi_actual_sku_sku_id_sku')),
    sa.ForeignKeyConstraint(['store_id'], ['store.id'], name=op.f('fk_bi_actual_sku_store_id_store')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bi_actual_sku'))
    )
    op.create_index(op.f('ix_bi_actual_sku_batch_id'), 'bi_actual_sku', ['batch_id'], unique=False)
    op.create_index('ix_bi_actual_sku_month_store', 'bi_actual_sku', ['month', 'store_id'], unique=False)
    op.create_table('import_staging',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('row_no', sa.Integer(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batch.id'], name=op.f('fk_import_staging_batch_id_import_batch'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_staging')),
    sa.UniqueConstraint('batch_id', 'row_no', name=op.f('uq_import_staging_batch_id_row_no'))
    )
    op.create_table('kingdee_actual',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('row_no', sa.Integer(), nullable=True),
    sa.Column('month', sa.Date(), nullable=False),
    sa.Column('department_id', sa.Integer(), nullable=True),
    sa.Column('store_id', sa.Integer(), nullable=True),
    sa.Column('site_id', sa.Integer(), nullable=True),
    sa.Column('customer_id', sa.Integer(), nullable=True),
    sa.Column('kingdee_code', sa.String(length=32), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=20, scale=6), nullable=False),
    sa.Column('unassigned', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('summary', sa.String(length=256), nullable=True),
    sa.CheckConstraint('extract(day from month) = 1', name=op.f('ck_kingdee_actual_month_first_day')),
    sa.ForeignKeyConstraint(['account_id'], ['budget_account.id'], name=op.f('fk_kingdee_actual_account_id_budget_account')),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batch.id'], name=op.f('fk_kingdee_actual_batch_id_import_batch')),
    sa.ForeignKeyConstraint(['customer_id'], ['b_customer.id'], name=op.f('fk_kingdee_actual_customer_id_b_customer')),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], name=op.f('fk_kingdee_actual_department_id_department')),
    sa.ForeignKeyConstraint(['site_id'], ['site.id'], name=op.f('fk_kingdee_actual_site_id_site')),
    sa.ForeignKeyConstraint(['store_id'], ['store.id'], name=op.f('fk_kingdee_actual_store_id_store')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_kingdee_actual'))
    )
    op.create_index(op.f('ix_kingdee_actual_batch_id'), 'kingdee_actual', ['batch_id'], unique=False)
    op.create_index('ix_kingdee_actual_month', 'kingdee_actual', ['month'], unique=False)
    # ### end Alembic commands ###
    # 循环外键（部门负责人 ↔ 用户、规则当前版本 ↔ 规则版本）在建表后补上
    op.create_foreign_key('fk_department_head_user_id_app_user', 'department', 'app_user', ['head_user_id'], ['id'])
    op.create_foreign_key('fk_rule_current_version', 'rule', 'rule_version', ['current_version_id'], ['id'])
    for stmt in TRIGGER_SQL:
        op.execute(stmt)
    _seed_roles()
    _seed_preset_rules()


def downgrade() -> None:
    for stmt in DROP_TRIGGER_SQL:
        op.execute(stmt)
    op.drop_constraint('fk_rule_current_version', 'rule', type_='foreignkey')
    op.drop_constraint('fk_department_head_user_id_app_user', 'department', type_='foreignkey')
    op.drop_index('ix_kingdee_actual_month', table_name='kingdee_actual')
    op.drop_index(op.f('ix_kingdee_actual_batch_id'), table_name='kingdee_actual')
    op.drop_table('kingdee_actual')
    op.drop_table('import_staging')
    op.drop_index('ix_bi_actual_sku_month_store', table_name='bi_actual_sku')
    op.drop_index(op.f('ix_bi_actual_sku_batch_id'), table_name='bi_actual_sku')
    op.drop_table('bi_actual_sku')
    op.drop_index('ix_bi_actual_agg_month_store', table_name='bi_actual_agg')
    op.drop_table('bi_actual_agg')
    op.drop_table('alert')
    op.drop_index('ix_import_batch_source_period_status', table_name='import_batch')
    op.drop_table('import_batch')
    op.drop_index(op.f('ix_reserve_usage_reserve_id'), table_name='reserve_usage')
    op.drop_table('reserve_usage')
    op.drop_index(op.f('ix_filling_unit_task_id'), table_name='filling_unit')
    op.drop_index(op.f('ix_filling_unit_reviewer_id'), table_name='filling_unit')
    op.drop_index(op.f('ix_filling_unit_filler_id'), table_name='filling_unit')
    op.drop_index(op.f('ix_filling_unit_adjustment_id'), table_name='filling_unit')
    op.drop_table('filling_unit')
    op.drop_index('uq_target_adjustment_open_year', table_name='target_adjustment', postgresql_where=sa.text("status IN ('in_progress', 'pending_ceo')"))
    op.drop_index('uq_target_adjustment_effective_quarter', table_name='target_adjustment', postgresql_where=sa.text("status = 'effective'"))
    op.drop_table('target_adjustment')
    op.drop_table('snapshot_month')
    op.drop_index('uq_rule_version_pending', table_name='rule_version', postgresql_where=sa.text("status IN ('pending', 'pending_ceo')"))
    op.drop_index('uq_rule_version_effective', table_name='rule_version', postgresql_where=sa.text("status = 'effective'"))
    op.drop_table('rule_version')
    op.drop_index(op.f('ix_reserve_version_id'), table_name='reserve')
    op.drop_table('reserve')
    op.drop_index('ix_platform_unit_version_store_month', table_name='platform_unit')
    op.drop_table('platform_unit')
    op.drop_table('dept_expense')
    op.drop_table('company_other_pl')
    op.drop_table('channel_site_ratio')
    op.drop_table('channel_category_ratio')
    op.drop_index('uq_budget_task_open_year', table_name='budget_task', postgresql_where=sa.text("status IN ('in_progress', 'pending_ceo')"))
    op.drop_table('budget_task')
    op.drop_table('b2b_unit')
    op.drop_table('variance_note')
    op.drop_index(op.f('ix_user_session_user_id'), table_name='user_session')
    op.drop_table('user_session')
    op.drop_index(op.f('ix_user_scope_user_id'), table_name='user_scope')
    op.drop_table('user_scope')
    op.drop_table('user_role')
    op.drop_index(op.f('ix_sku_spu_id'), table_name='sku')
    op.drop_table('sku')
    op.drop_table('rule')
    op.drop_table('kingdee_account_map')
    op.drop_table('fx_budget')
    op.drop_table('fx_actual')
    op.drop_index('uq_budget_version_rolling_quarter', table_name='budget_version', postgresql_where=sa.text("type IN ('rolling_draft', 'snapshot')"))
    op.drop_table('budget_version')
    op.drop_index('ix_approval_record_object', table_name='approval_record')
    op.drop_table('approval_record')
    op.drop_index(op.f('ix_store_channel_id'), table_name='store')
    op.drop_table('store')
    op.drop_index(op.f('ix_spu_category_id'), table_name='spu')
    op.drop_table('spu')
    op.drop_index(op.f('ix_b_customer_department_id'), table_name='b_customer')
    op.drop_table('b_customer')
    op.drop_table('app_user')
    op.drop_table('site')
    op.drop_table('role')
    op.drop_index('ix_notification_outbox_due', table_name='notification_outbox')
    op.drop_index('ix_notification_outbox_biz', table_name='notification_outbox')
    op.drop_table('notification_outbox')
    op.drop_table('department')
    op.drop_table('channel')
    op.drop_table('category')
    op.drop_table('budget_account')
    op.drop_index('ix_audit_log_occurred_at', table_name='audit_log')
    op.drop_index('ix_audit_log_object', table_name='audit_log')
    op.drop_table('audit_log')
    # ### end Alembic commands ###
