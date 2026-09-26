"""Remove unique constraint on test_runs

Revision ID: remove_test_runs_unique
Revises: 0172a5ad043e
Create Date: 2026-09-10

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'remove_test_runs_unique'
down_revision = '0172a5ad043e'
branch_labels = None
depends_on = None


def upgrade():
    # 删除唯一约束，允许同一提示词版本和素材多次测试
    op.drop_constraint('uq_test_runs_version_asset', 'test_runs', schema='prompt_library')


def downgrade():
    # 恢复唯一约束
    op.create_unique_constraint(
        'uq_test_runs_version_asset',
        'test_runs',
        ['prompt_version_id', 'input_asset_id'],
        schema='prompt_library'
    )
