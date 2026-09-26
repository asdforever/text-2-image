"""新增可发布的生成配置域。"""

from alembic import op


revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS generation_config")
    op.execute(
        """
        CREATE TABLE generation_config.config_versions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id),
          version_no integer NOT NULL,
          content jsonb NOT NULL,
          content_sha256 char(64) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_config_versions_workspace_version UNIQUE (workspace_id, version_no),
          CONSTRAINT config_versions_version_no_check CHECK (version_no > 0),
          CONSTRAINT config_versions_content_sha256_check CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX config_versions_workspace_version_idx "
        "ON generation_config.config_versions(workspace_id, version_no DESC)"
    )
    op.execute(
        "CREATE INDEX config_versions_content_sha256_idx "
        "ON generation_config.config_versions(content_sha256)"
    )
    op.execute(
        """
        CREATE TABLE generation_config.config_drafts (
          workspace_id uuid PRIMARY KEY REFERENCES suite_workbench.workspaces(id),
          base_version_no integer NOT NULL,
          content jsonb NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT config_drafts_base_version_no_check CHECK (base_version_no > 0)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS generation_config.config_drafts")
    op.execute("DROP TABLE IF EXISTS generation_config.config_versions")
    op.execute("DROP SCHEMA IF EXISTS generation_config")
