"""Preserve multiple reverse plans and generation batches."""

from alembic import op

revision = "20261007_reverse_batches"
down_revision = "20260930_reverse_execution"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE project_workbench.reverse_execution_plans DROP CONSTRAINT reverse_execution_plans_workspace_id_project_id_key")
    op.execute("CREATE INDEX reverse_execution_plans_project_idx ON project_workbench.reverse_execution_plans(workspace_id,project_id,created_at DESC)")
    op.execute("""
        CREATE TABLE project_workbench.reverse_execution_batches (
            id uuid PRIMARY KEY,
            workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
            plan_id uuid NOT NULL REFERENCES project_workbench.reverse_execution_plans(id) ON DELETE CASCADE,
            batch_no integer NOT NULL CHECK(batch_no > 0),
            document jsonb NOT NULL,
            revision integer NOT NULL DEFAULT 1 CHECK(revision > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(plan_id,batch_no)
        )
    """)
    op.execute("CREATE INDEX reverse_execution_batches_project_idx ON project_workbench.reverse_execution_batches(workspace_id,project_id,created_at DESC)")


def downgrade():
    # Reverting to a single-plan schema must never silently discard plans.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM project_workbench.reverse_execution_plans GROUP BY workspace_id,project_id HAVING count(*) > 1)
        THEN RAISE EXCEPTION 'Cannot downgrade while a project has multiple reverse plans'; END IF;
    END $$""")
    op.execute("DROP TABLE project_workbench.reverse_execution_batches")
    op.execute("DROP INDEX project_workbench.reverse_execution_plans_project_idx")
    op.execute("ALTER TABLE project_workbench.reverse_execution_plans ADD CONSTRAINT reverse_execution_plans_workspace_id_project_id_key UNIQUE(workspace_id,project_id)")
