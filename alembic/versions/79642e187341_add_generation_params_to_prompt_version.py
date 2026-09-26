"""add_generation_params_to_prompt_version

Revision ID: 79642e187341
Revises: merge_prompt_asset_heads
Create Date: 2026-09-12 11:18:19.714003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '79642e187341'
down_revision: Union[str, None] = 'merge_prompt_asset_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'prompt_versions',
        sa.Column('generation_params', sa.JSON(), nullable=False, server_default='{}'),
        schema='prompt_library'
    )


def downgrade() -> None:
    op.drop_column('prompt_versions', 'generation_params', schema='prompt_library')
