"""业财分析工作区：bizfin_section 按部分存 JSON 文档（REQ-F15-01、DEC-029）。

Revision ID: 0004
Revises: 0003
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bizfin_section",
        sa.Column("key", sa.String(16), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("key IN ('indicators', 'biz_dim', 'policy', 'advice', 'keywork')",
                           name=op.f("ck_bizfin_section_key")),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_bizfin_section")),
    )


def downgrade() -> None:
    op.drop_table("bizfin_section")
