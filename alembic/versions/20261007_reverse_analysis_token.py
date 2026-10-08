"""Keep reverse analysis cleanup scoped to its owning attempt."""

from alembic import op

revision = "20261007_reverse_analysis_token"
down_revision = "20261007_reverse_batches"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE project_workbench.reverse_projects ADD COLUMN analysis_token uuid")


def downgrade():
    op.execute("ALTER TABLE project_workbench.reverse_projects DROP COLUMN analysis_token")
