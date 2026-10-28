"""业财分析删除「经营建议」模块（用户 2026-10-28，requirements revision 7）：bizfin_section 不再接受 advice 部分。

已保存的经营建议台账随模块一并删除（模块入口已移除，无其他读取方）。

Revision ID: 0005
Revises: 0004
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "key IN ('indicators', 'biz_dim', 'policy', 'advice', 'keywork')"
_NEW = "key IN ('indicators', 'biz_dim', 'policy', 'keywork')"


def upgrade() -> None:
    op.execute("DELETE FROM bizfin_section WHERE key = 'advice'")
    op.execute(f"ALTER TABLE bizfin_section DROP CONSTRAINT ck_bizfin_section_key, "
               f"ADD CONSTRAINT ck_bizfin_section_key CHECK ({_NEW})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE bizfin_section DROP CONSTRAINT ck_bizfin_section_key, "
               f"ADD CONSTRAINT ck_bizfin_section_key CHECK ({_OLD})")
