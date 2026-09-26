"""新增图片编辑会话与正式产品库。"""

from alembic import op


revision = "f2a3b4c5d6e7"
# 阶段六迁移接在工作台状态迁移之后，保持 Alembic 单一线性 head。
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_workbench.image_edit_sessions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          source_version_id uuid NOT NULL,
          source_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          operations_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb,
          revision integer NOT NULL DEFAULT 1,
          status varchar(30) NOT NULL DEFAULT 'draft',
          archived_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT image_edit_sessions_revision_check CHECK (revision > 0),
          CONSTRAINT image_edit_sessions_status_check CHECK (status IN ('draft','submitted','queued','generating','succeeded','failed','archived'))
        )
        """
    )
    op.execute("CREATE INDEX image_edit_sessions_project_status_idx ON project_workbench.image_edit_sessions(project_id, status, created_at)")
    op.execute(
        """
        CREATE TABLE project_workbench.image_edit_operations (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          session_id uuid NOT NULL REFERENCES project_workbench.image_edit_sessions(id) ON DELETE CASCADE,
          ordinal integer NOT NULL,
          operation_type varchar(40) NOT NULL,
          payload jsonb NOT NULL DEFAULT '{}'::jsonb,
          revision integer NOT NULL DEFAULT 1,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT image_edit_operations_revision_check CHECK (revision > 0),
          CONSTRAINT image_edit_operations_ordinal_check CHECK (ordinal > 0),
          CONSTRAINT uq_image_edit_operations_ordinal UNIQUE (session_id, ordinal)
        )
        """
    )
    op.execute("CREATE INDEX image_edit_operations_session_idx ON project_workbench.image_edit_operations(session_id, ordinal)")
    op.execute(
        """
        CREATE TABLE project_workbench.image_ocr_results (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          session_id uuid NOT NULL REFERENCES project_workbench.image_edit_sessions(id) ON DELETE CASCADE,
          source_version_id uuid NOT NULL,
          request_fingerprint varchar(128) NOT NULL,
          text text NOT NULL DEFAULT '',
          regions jsonb NOT NULL DEFAULT '[]'::jsonb,
          provider_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_image_ocr_results_request UNIQUE (session_id, source_version_id, request_fingerprint)
        )
        """
    )
    op.execute("CREATE INDEX image_ocr_results_session_source_idx ON project_workbench.image_ocr_results(session_id, source_version_id, created_at)")
    op.execute(
        """
        CREATE TABLE project_workbench.image_edit_tasks (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          session_id uuid NOT NULL REFERENCES project_workbench.image_edit_sessions(id) ON DELETE CASCADE,
          revision integer NOT NULL DEFAULT 1,
          status varchar(30) NOT NULL DEFAULT 'queued',
          operations_snapshot jsonb NOT NULL DEFAULT '[]'::jsonb,
          source_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          prompt_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          current_version_id uuid,
          final_version_id uuid,
          archived_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT image_edit_tasks_revision_check CHECK (revision > 0),
          CONSTRAINT image_edit_tasks_status_check CHECK (status IN ('queued','generating','succeeded','failed','cancelled','archived'))
        )
        """
    )
    op.execute("CREATE INDEX image_edit_tasks_project_status_idx ON project_workbench.image_edit_tasks(project_id, status, created_at)")
    op.execute(
        """
        CREATE TABLE project_workbench.image_edit_attempts (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          task_id uuid NOT NULL REFERENCES project_workbench.image_edit_tasks(id) ON DELETE CASCADE,
          attempt_number integer NOT NULL,
          status varchar(30) NOT NULL DEFAULT 'queued',
          provider_task_id varchar(200),
          error_message text,
          provider_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          CONSTRAINT image_edit_attempts_number_check CHECK (attempt_number > 0),
          CONSTRAINT image_edit_attempts_status_check CHECK (status IN ('queued','generating','succeeded','failed','cancelled')),
          CONSTRAINT uq_image_edit_attempts_number UNIQUE (task_id, attempt_number)
        )
        """
    )
    op.execute("CREATE INDEX image_edit_attempts_task_idx ON project_workbench.image_edit_attempts(task_id, created_at)")
    op.execute(
        """
        CREATE TABLE project_workbench.image_edit_versions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          task_id uuid NOT NULL REFERENCES project_workbench.image_edit_tasks(id) ON DELETE CASCADE,
          attempt_id uuid REFERENCES project_workbench.image_edit_attempts(id) ON DELETE SET NULL,
          version_number integer NOT NULL,
          object_key text NOT NULL DEFAULT '',
          preview_url text NOT NULL DEFAULT '',
          sha256 char(64) NOT NULL DEFAULT '',
          width integer NOT NULL DEFAULT 1,
          height integer NOT NULL DEFAULT 1,
          mime_type varchar(100) NOT NULL DEFAULT 'image/png',
          source_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          prompt_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          is_current boolean NOT NULL DEFAULT false,
          is_final boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT image_edit_versions_number_check CHECK (version_number > 0),
          CONSTRAINT uq_image_edit_versions_number UNIQUE (task_id, version_number)
        )
        """
    )
    op.execute("CREATE INDEX image_edit_versions_task_idx ON project_workbench.image_edit_versions(task_id, created_at)")
    op.execute(
        """
        CREATE TABLE project_workbench.product_libraries (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          name varchar(200) NOT NULL,
          description text NOT NULL DEFAULT '',
          library_type varchar(20) NOT NULL DEFAULT 'production',
          archived_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT product_libraries_type_check CHECK (library_type = 'production')
        )
        """
    )
    op.execute("CREATE INDEX product_libraries_workspace_active_idx ON project_workbench.product_libraries(workspace_id, archived_at)")
    op.execute(
        """
        CREATE TABLE project_workbench.products (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          library_id uuid NOT NULL REFERENCES project_workbench.product_libraries(id) ON DELETE CASCADE,
          project_id uuid REFERENCES project_workbench.projects(id) ON DELETE SET NULL,
          name varchar(200) NOT NULL,
          product_type varchar(30) NOT NULL DEFAULT 'product',
          metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
          archived_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT products_type_check CHECK (product_type IN ('product','sku','collection'))
        )
        """
    )
    op.execute("CREATE INDEX products_library_active_idx ON project_workbench.products(library_id, archived_at)")
    op.execute(
        """
        CREATE TABLE project_workbench.product_versions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid REFERENCES project_workbench.projects(id) ON DELETE SET NULL,
          product_id uuid NOT NULL REFERENCES project_workbench.products(id) ON DELETE CASCADE,
          source_version_id uuid NOT NULL,
          source_task_id uuid,
          source_attempt_id uuid,
          version_number integer NOT NULL,
          product_type varchar(30) NOT NULL,
          status varchar(20) NOT NULL DEFAULT 'published',
          object_key text NOT NULL,
          preview_url text NOT NULL DEFAULT '',
          mime_type varchar(100) NOT NULL DEFAULT 'image/png',
          file_size integer,
          width integer,
          height integer,
          source_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          prompt_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          config_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          idempotency_key varchar(200) UNIQUE,
          is_current boolean NOT NULL DEFAULT false,
          archived_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT product_versions_number_check CHECK (version_number > 0),
          CONSTRAINT product_versions_type_check CHECK (product_type IN ('hero','detail','white_background','scene','edit')),
          CONSTRAINT product_versions_status_check CHECK (status IN ('published','archived')),
          CONSTRAINT uq_product_versions_number UNIQUE (product_id, version_number)
        )
        """
    )
    op.execute("CREATE INDEX product_versions_product_type_idx ON project_workbench.product_versions(product_id, product_type, status, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_workbench.product_versions")
    op.execute("DROP TABLE IF EXISTS project_workbench.products")
    op.execute("DROP TABLE IF EXISTS project_workbench.product_libraries")
    op.execute("DROP TABLE IF EXISTS project_workbench.image_edit_versions")
    op.execute("DROP TABLE IF EXISTS project_workbench.image_edit_attempts")
    op.execute("DROP TABLE IF EXISTS project_workbench.image_edit_tasks")
    op.execute("DROP TABLE IF EXISTS project_workbench.image_ocr_results")
    op.execute("DROP TABLE IF EXISTS project_workbench.image_edit_operations")
    op.execute("DROP TABLE IF EXISTS project_workbench.image_edit_sessions")
