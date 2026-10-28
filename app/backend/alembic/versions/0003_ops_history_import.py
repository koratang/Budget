"""经营历史表导入：import_batch.source 增加 ops-history，并记录表格所属年度。

经营历史表（各渠道店铺月度毛利明细 + 管理费用明细）按年度整表上传，表内只有「1月…12月」没有年份，
上传时由财务BP选择年度，校验时据此确定期间。

Revision ID: 0003
Revises: 0002
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "source IN ('kingdee', 'kingdee-history', 'bi', 'sku', 'template')"
_NEW = "source IN ('kingdee', 'kingdee-history', 'ops-history', 'bi', 'sku', 'template')"


def upgrade() -> None:
    op.execute(f"ALTER TABLE import_batch DROP CONSTRAINT ck_import_batch_source, "
               f"ADD CONSTRAINT ck_import_batch_source CHECK ({_NEW})")
    op.add_column("import_batch", sa.Column("data_year", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("import_batch", "data_year")
    op.execute(f"ALTER TABLE import_batch DROP CONSTRAINT ck_import_batch_source, "
               f"ADD CONSTRAINT ck_import_batch_source CHECK ({_OLD})")
