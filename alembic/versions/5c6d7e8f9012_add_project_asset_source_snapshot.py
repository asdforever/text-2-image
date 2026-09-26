"""保存项目资产的外部来源和版本快照。"""

from alembic import op


revision = "5c6d7e8f9012"
down_revision = "4b5c6d7e8f90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE project_workbench.project_assets ADD COLUMN IF NOT EXISTS source_kind varchar(30) NOT NULL DEFAULT 'upload'")
    op.execute("ALTER TABLE project_workbench.project_assets ADD COLUMN IF NOT EXISTS source_library_id varchar(200)")
    op.execute("ALTER TABLE project_workbench.project_assets ADD COLUMN IF NOT EXISTS source_resource_id varchar(200)")
    op.execute("ALTER TABLE project_workbench.project_assets ADD COLUMN IF NOT EXISTS source_resource_version_id varchar(200)")
    op.execute("ALTER TABLE project_workbench.project_assets ADD COLUMN IF NOT EXISTS source_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE project_workbench.project_assets DROP COLUMN IF EXISTS source_snapshot")
    op.execute("ALTER TABLE project_workbench.project_assets DROP COLUMN IF EXISTS source_resource_version_id")
    op.execute("ALTER TABLE project_workbench.project_assets DROP COLUMN IF EXISTS source_resource_id")
    op.execute("ALTER TABLE project_workbench.project_assets DROP COLUMN IF EXISTS source_library_id")
    op.execute("ALTER TABLE project_workbench.project_assets DROP COLUMN IF EXISTS source_kind")
