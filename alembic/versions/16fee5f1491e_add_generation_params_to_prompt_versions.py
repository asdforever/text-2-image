"""add_generation_params_to_prompt_versions

Revision ID: 16fee5f1491e
Revises: 79642e187341
Create Date: 2026-09-12 11:27:06.955648
"""
from typing import Sequence, Union

revision: str = '16fee5f1491e'
down_revision: Union[str, None] = '79642e187341'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 79642e187341 已添加该列。本 revision 保留在线性历史中，但不重复 DDL。
    pass


def downgrade() -> None:
    # 对应 upgrade 无操作；列由 79642e187341 的 downgrade 负责删除。
    pass
