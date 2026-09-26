"""为图片编辑任务保存提交幂等键，使 Postgres 仓储也能阻止重复提交。"""

from alembic import op


revision = "a1b2c3d4e5f6"
down_revision = "5c6d7e8f9012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE project_workbench.image_edit_tasks "
        "ADD COLUMN IF NOT EXISTS submit_idempotency_key varchar(200)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_image_edit_tasks_submit_idempotency "
        "ON project_workbench.image_edit_tasks (session_id, submit_idempotency_key)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS project_workbench.uq_image_edit_tasks_submit_idempotency"
    )
    op.execute(
        "ALTER TABLE project_workbench.image_edit_tasks "
        "DROP COLUMN IF EXISTS submit_idempotency_key"
    )
