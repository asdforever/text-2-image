"""remove_prompt_file_sync_fields

Revision ID: b5467b039772
Revises: f9a8b7c6d5e4
Create Date: 2026-09-16 13:55:23.633755
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b5467b039772'
down_revision: Union[str, None] = 'f9a8b7c6d5e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove file sync related columns from prompt_versions
    op.drop_column('prompt_versions', 'file_path', schema='prompt_library')
    op.drop_column('prompt_versions', 'file_sync_status', schema='prompt_library')
    op.drop_column('prompt_versions', 'file_sync_error', schema='prompt_library')
    op.drop_column('prompt_versions', 'synced_at', schema='prompt_library')


def downgrade() -> None:
    # Restore file sync columns if needed
    op.add_column('prompt_versions', sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True), schema='prompt_library')
    op.add_column('prompt_versions', sa.Column('file_sync_error', sa.Text(), nullable=True), schema='prompt_library')
    op.add_column('prompt_versions', sa.Column('file_sync_status', sa.String(20), nullable=False, server_default='pending'), schema='prompt_library')
    op.add_column('prompt_versions', sa.Column('file_path', sa.Text(), nullable=False, server_default=''), schema='prompt_library')
