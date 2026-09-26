"""保存画布生成步骤的提示词版本、图片版本和当前选择。"""
from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE project_workbench.canvas_generation_tracks (
            workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
            project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
            step_id text NOT NULL,
            state jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, project_id, step_id)
        )
    """)


def downgrade():
    op.execute("DROP TABLE project_workbench.canvas_generation_tracks")
