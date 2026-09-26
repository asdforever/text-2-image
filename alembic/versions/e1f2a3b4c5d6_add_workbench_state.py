"""新增工作台任务状态、画布布局和资源引用。"""

from alembic import op


revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_workbench.workbench_tasks (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          plan_snapshot_id uuid REFERENCES project_workbench.suite_plans(id) ON DELETE SET NULL,
          plan_item_id uuid,
          ordinal integer NOT NULL DEFAULT 1,
          image_type varchar(30) NOT NULL DEFAULT 'detail',
          title varchar(300) NOT NULL,
          purpose text NOT NULL DEFAULT '',
          prompt_draft text NOT NULL DEFAULT '',
          prompt_revision integer NOT NULL DEFAULT 1,
          source_input_image_id uuid,
          generation_params jsonb NOT NULL DEFAULT '{}'::jsonb,
          status varchar(30) NOT NULL DEFAULT 'draft',
          current_version_id uuid,
          final_version_id uuid,
          archived_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT workbench_tasks_status_check CHECK (
            status IN ('draft', 'queued', 'generating', 'succeeded', 'failed', 'cancelled', 'archived')
          ),
          CONSTRAINT workbench_tasks_revision_check CHECK (prompt_revision > 0),
          CONSTRAINT uq_workbench_tasks_plan_item UNIQUE (project_id, plan_snapshot_id, plan_item_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX workbench_tasks_project_status_idx ON project_workbench.workbench_tasks(project_id, status, ordinal)"
    )
    op.execute(
        """
        CREATE TABLE project_workbench.workbench_task_versions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          task_id uuid NOT NULL REFERENCES project_workbench.workbench_tasks(id) ON DELETE CASCADE,
          batch_id uuid REFERENCES project_workbench.generation_batches(id) ON DELETE SET NULL,
          slot_id uuid REFERENCES project_workbench.generation_image_slots(id) ON DELETE SET NULL,
          attempt_id uuid,
          version_number integer NOT NULL,
          object_key text NOT NULL DEFAULT '',
          process_object_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
          preview_url text NOT NULL DEFAULT '',
          sha256 char(64) NOT NULL DEFAULT '',
          width integer NOT NULL DEFAULT 1,
          height integer NOT NULL DEFAULT 1,
          mime_type varchar(100) NOT NULL DEFAULT 'image/png',
          prompt_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          context_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          is_current boolean NOT NULL DEFAULT false,
          is_final boolean NOT NULL DEFAULT false,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT workbench_task_versions_number_check CHECK (version_number > 0),
          CONSTRAINT uq_workbench_task_versions_number UNIQUE (task_id, version_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX workbench_task_versions_task_created_idx ON project_workbench.workbench_task_versions(task_id, created_at)"
    )
    op.execute(
        """
        CREATE TABLE project_workbench.workbench_layouts (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          layout_version integer NOT NULL DEFAULT 1,
          viewport jsonb NOT NULL DEFAULT '{}'::jsonb,
          nodes jsonb NOT NULL DEFAULT '[]'::jsonb,
          groups jsonb NOT NULL DEFAULT '[]'::jsonb,
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT workbench_layouts_version_check CHECK (layout_version > 0),
          CONSTRAINT uq_workbench_layouts_project UNIQUE (project_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE project_workbench.workbench_references (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          target_type varchar(20) NOT NULL,
          target_id uuid NOT NULL,
          resource_type varchar(40) NOT NULL,
          resource_id uuid NOT NULL,
          resource_version varchar(120) NOT NULL DEFAULT '',
          source_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          archived_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT workbench_references_target_type_check CHECK (target_type IN ('plan', 'task')),
          CONSTRAINT workbench_references_resource_type_check CHECK (
            resource_type IN ('prompt_template', 'input_image', 'base_image', 'task_image_version', 'process_image', 'reverse_reference_asset')
          ),
          CONSTRAINT uq_workbench_references_resource UNIQUE (
            project_id, target_type, target_id, resource_type, resource_id, resource_version
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX workbench_references_target_idx ON project_workbench.workbench_references(project_id, target_type, target_id, archived_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_workbench.workbench_references")
    op.execute("DROP TABLE IF EXISTS project_workbench.workbench_layouts")
    op.execute("DROP TABLE IF EXISTS project_workbench.workbench_task_versions")
    op.execute("DROP TABLE IF EXISTS project_workbench.workbench_tasks")
