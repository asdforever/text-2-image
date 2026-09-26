"""新增工作台项目和项目资产域。"""

from alembic import op


revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS project_workbench")
    op.execute(
        """
        CREATE TABLE project_workbench.projects (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id),
          name varchar(200) NOT NULL,
          status varchar(20) NOT NULL DEFAULT 'active',
          archived_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT projects_status_check CHECK (status IN ('active', 'archived'))
        )
        """
    )
    op.execute(
        "CREATE INDEX projects_workspace_status_idx "
        "ON project_workbench.projects(workspace_id, status, updated_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE project_workbench.asset_objects (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id),
          storage_key text NOT NULL UNIQUE,
          original_filename varchar(500) NOT NULL,
          media_type varchar(100) NOT NULL,
          byte_size bigint NOT NULL CHECK (byte_size >= 0),
          width integer NOT NULL CHECK (width > 0),
          height integer NOT NULL CHECK (height > 0),
          sha256 char(64) NOT NULL,
          state varchar(20) NOT NULL DEFAULT 'available',
          cleanup_attempted_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT asset_objects_state_check
            CHECK (state IN ('available', 'cleanup_pending', 'cleaned')),
          CONSTRAINT asset_objects_sha256_check CHECK (sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX asset_objects_workspace_sha256_idx "
        "ON project_workbench.asset_objects(workspace_id, sha256)"
    )
    op.execute(
        """
        CREATE TABLE project_workbench.project_assets (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          object_id uuid NOT NULL REFERENCES project_workbench.asset_objects(id) ON DELETE RESTRICT,
          kind varchar(30) NOT NULL,
          source_asset_id uuid REFERENCES project_workbench.project_assets(id) ON DELETE RESTRICT,
          generation_snapshot_id uuid,
          state varchar(20) NOT NULL DEFAULT 'available',
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT project_assets_kind_check
            CHECK (kind IN ('source', 'white_background', 'generated')),
          CONSTRAINT project_assets_state_check
            CHECK (state IN ('available', 'cleanup_pending', 'deleted')),
          CONSTRAINT project_assets_white_background_source_check
            CHECK (kind <> 'white_background' OR source_asset_id IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE INDEX project_assets_project_kind_idx "
        "ON project_workbench.project_assets(project_id, kind, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX project_assets_object_idx "
        "ON project_workbench.project_assets(object_id)"
    )
    op.execute(
        """
        CREATE TABLE project_workbench.project_asset_selections (
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          role varchar(30) NOT NULL,
          project_asset_id uuid NOT NULL REFERENCES project_workbench.project_assets(id) ON DELETE RESTRICT,
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (project_id, role),
          CONSTRAINT project_asset_selections_role_check
            CHECK (role IN ('source', 'white_background', 'generated'))
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_workbench.project_asset_selections")
    op.execute("DROP TABLE IF EXISTS project_workbench.project_assets")
    op.execute("DROP TABLE IF EXISTS project_workbench.asset_objects")
    op.execute("DROP TABLE IF EXISTS project_workbench.projects")
    op.execute("DROP SCHEMA IF EXISTS project_workbench")
