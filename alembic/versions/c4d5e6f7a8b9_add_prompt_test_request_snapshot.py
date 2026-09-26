"""保存提示词测试任务的请求快照。"""

from alembic import op


revision = "c4d5e6f7a8b9"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE prompt_library.test_runs "
        "ADD COLUMN IF NOT EXISTS request_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE prompt_library.test_runs "
        "DROP COLUMN IF EXISTS request_snapshot"
    )
