"""persist project reverse execution plans"""

from alembic import op


revision = "20260930_reverse_execution"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_workbench.reverse_execution_plans (
            id uuid PRIMARY KEY,
            workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
            reverse_version_id uuid NOT NULL REFERENCES project_workbench.reverse_versions(id) ON DELETE RESTRICT,
            document jsonb NOT NULL,
            revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (workspace_id, project_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX reverse_execution_plans_version_idx "
        "ON project_workbench.reverse_execution_plans(workspace_id, reverse_version_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS project_workbench.reverse_execution_plans_version_idx")
    op.execute("DROP TABLE IF EXISTS project_workbench.reverse_execution_plans")
