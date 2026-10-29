"""业财分析删除「重点工作进度」「业财数据管理」（用户 2026-10-29，requirements revision 8）：bizfin_section 不再接受 keywork 部分。

已保存的重点工作台账随模块一并删除（模块入口已移除，无其他读取方）。

Revision ID: 0006
Revises: 0005
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "key IN ('indicators', 'biz_dim', 'policy', 'keywork')"
_NEW = "key IN ('indicators', 'biz_dim', 'policy')"


def upgrade() -> None:
    op.execute("DELETE FROM bizfin_section WHERE key = 'keywork'")
    op.execute(f"ALTER TABLE bizfin_section DROP CONSTRAINT ck_bizfin_section_key, "
               f"ADD CONSTRAINT ck_bizfin_section_key CHECK ({_NEW})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE bizfin_section DROP CONSTRAINT ck_bizfin_section_key, "
               f"ADD CONSTRAINT ck_bizfin_section_key CHECK ({_OLD})")
