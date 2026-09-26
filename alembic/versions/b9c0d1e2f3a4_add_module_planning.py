"""Persist planning master runs and allow the complete suite module catalog."""
from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE project_workbench.suite_plans DROP CONSTRAINT suite_plans_module_count_check")
    op.execute("ALTER TABLE project_workbench.suite_plans ADD CONSTRAINT suite_plans_module_count_check CHECK (requested_module_count > 0)")
    op.execute("ALTER TABLE project_workbench.suite_plan_modules DROP CONSTRAINT suite_plan_modules_position_check")
    op.execute("ALTER TABLE project_workbench.suite_plan_modules ADD CONSTRAINT suite_plan_modules_position_check CHECK (position > 0)")
    op.execute("""
        CREATE TABLE project_workbench.module_plans (
            id uuid PRIMARY KEY,
            workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
            project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
            request_key varchar(200) NOT NULL,
            fingerprint char(64) NOT NULL,
            mode varchar(10) NOT NULL CHECK (mode IN ('hero', 'suite')),
            document jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (workspace_id, project_id, request_key)
        )
    """)
    op.execute("CREATE INDEX module_plans_latest_idx ON project_workbench.module_plans (workspace_id, project_id, mode, created_at DESC)")


def downgrade():
    # Refuse downgrade with large plans, instead of deleting user data to fit the old limit.
    op.execute("ALTER TABLE project_workbench.suite_plans DROP CONSTRAINT suite_plans_module_count_check")
    op.execute("ALTER TABLE project_workbench.suite_plans ADD CONSTRAINT suite_plans_module_count_check CHECK (requested_module_count BETWEEN 1 AND 5)")
    op.execute("ALTER TABLE project_workbench.suite_plan_modules DROP CONSTRAINT suite_plan_modules_position_check")
    op.execute("ALTER TABLE project_workbench.suite_plan_modules ADD CONSTRAINT suite_plan_modules_position_check CHECK (position BETWEEN 1 AND 5)")
    op.execute("DROP TABLE project_workbench.module_plans")
