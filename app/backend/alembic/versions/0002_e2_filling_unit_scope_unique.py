"""填报单位唯一性改为部分唯一索引（FLOW-19 验收发现）。

0001 的两条唯一约束 (task_id, unit_type, scope_object_id) 与 (adjustment_id, unit_type, scope_object_id) 都是
NULLS NOT DISTINCT，而 task_id / adjustment_id 二选一、另一列恒为 NULL：第二次目标调整（如 Q1 已调整后再发起 Q2）
与第一次的调整单位在 task_id 约束上冲突，发起时报错；第二个编制任务的单位同理在 adjustment_id 约束上冲突。
改为各自只在本外键非空时生效的部分唯一索引。

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_filling_unit_task_scope", "filling_unit", type_="unique")
    op.drop_constraint("uq_filling_unit_adjustment_scope", "filling_unit", type_="unique")
    op.create_index("uq_filling_unit_task_scope", "filling_unit", ["task_id", "unit_type", "scope_object_id"],
                    unique=True, postgresql_nulls_not_distinct=True, postgresql_where=sa.text("task_id IS NOT NULL"))
    op.create_index("uq_filling_unit_adjustment_scope", "filling_unit",
                    ["adjustment_id", "unit_type", "scope_object_id"], unique=True,
                    postgresql_nulls_not_distinct=True, postgresql_where=sa.text("adjustment_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_filling_unit_adjustment_scope", table_name="filling_unit")
    op.drop_index("uq_filling_unit_task_scope", table_name="filling_unit")
    op.create_unique_constraint("uq_filling_unit_task_scope", "filling_unit", ["task_id", "unit_type", "scope_object_id"],
                                postgresql_nulls_not_distinct=True)
    op.create_unique_constraint("uq_filling_unit_adjustment_scope", "filling_unit",
                                ["adjustment_id", "unit_type", "scope_object_id"], postgresql_nulls_not_distinct=True)
