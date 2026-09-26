"""允许没有原图关联的外部白底图进入项目资产。"""

from alembic import op


revision = "4b5c6d7e8f90"
down_revision = "3af2e3c6054f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE project_workbench.project_assets "
        "DROP CONSTRAINT IF EXISTS project_assets_white_background_source_check"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE project_workbench.project_assets "
        "ADD CONSTRAINT project_assets_white_background_source_check "
        "CHECK (kind <> 'white_background' OR source_asset_id IS NOT NULL)"
    )
