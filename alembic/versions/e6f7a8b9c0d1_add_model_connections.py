"""模型连接独立版本与加密密钥。"""
from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE generation_config.model_connections (
        id uuid PRIMARY KEY,
        workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
        base_url text NOT NULL,
        model_name text NOT NULL,
        protocol text NOT NULL CHECK (protocol = 'openai_images'),
        encrypted_key bytea NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )""")
    op.execute("CREATE INDEX model_connections_workspace_idx ON generation_config.model_connections(workspace_id)")


def downgrade():
    op.execute("DROP TABLE generation_config.model_connections")
