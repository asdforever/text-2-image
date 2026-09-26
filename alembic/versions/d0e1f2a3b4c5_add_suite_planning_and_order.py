"""新增详情页规划并扩展有序生成批次。"""

from alembic import op


revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_workbench.suite_plans (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL
            REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL
            REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          status varchar(30) NOT NULL DEFAULT 'compiling',
          revision integer NOT NULL DEFAULT 1,
          requested_module_count integer NOT NULL,
          compile_idempotency_key varchar(200) NOT NULL,
          compile_fingerprint char(64) NOT NULL,
          confirm_idempotency_key varchar(200),
          confirm_fingerprint char(64),
          snapshot jsonb NOT NULL,
          confirmed_snapshot jsonb,
          generation_batch_id uuid
            REFERENCES project_workbench.generation_batches(id) ON DELETE SET NULL,
          error_code varchar(80),
          error_message text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          confirmed_at timestamptz,
          CONSTRAINT suite_plans_status_check CHECK (
            status IN ('compiling', 'awaiting_confirmation', 'confirmed', 'failed')
          ),
          CONSTRAINT suite_plans_revision_check CHECK (revision > 0),
          CONSTRAINT suite_plans_module_count_check
            CHECK (requested_module_count BETWEEN 1 AND 5),
          CONSTRAINT uq_suite_plans_compile_idempotency
            UNIQUE (workspace_id, compile_idempotency_key),
          CONSTRAINT uq_suite_plans_confirm_idempotency
            UNIQUE (workspace_id, confirm_idempotency_key),
          CONSTRAINT suite_plans_compile_fingerprint_check
            CHECK (compile_fingerprint ~ '^[0-9a-f]{64}$'),
          CONSTRAINT suite_plans_confirm_fingerprint_check
            CHECK (confirm_fingerprint IS NULL OR confirm_fingerprint ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX suite_plans_project_latest_idx "
        "ON project_workbench.suite_plans(project_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE project_workbench.suite_plan_modules (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          plan_id uuid NOT NULL
            REFERENCES project_workbench.suite_plans(id) ON DELETE CASCADE,
          module_key varchar(120) NOT NULL,
          position integer NOT NULL,
          requested_image_count integer NOT NULL,
          revision integer NOT NULL DEFAULT 1,
          title varchar(300) NOT NULL,
          copy_summary text NOT NULL DEFAULT '',
          visual_direction text NOT NULL DEFAULT '',
          module_parameters jsonb NOT NULL DEFAULT '[]'::jsonb,
          prompt_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
          compiled_task_prompt text,
          compiler_output jsonb,
          current_task_prompt text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT suite_plan_modules_position_check CHECK (position BETWEEN 1 AND 5),
          CONSTRAINT suite_plan_modules_requested_image_count_check
            CHECK (requested_image_count BETWEEN 1 AND 4),
          CONSTRAINT suite_plan_modules_revision_check CHECK (revision > 0),
          CONSTRAINT uq_suite_plan_modules_plan_module UNIQUE (plan_id, module_key),
          CONSTRAINT uq_suite_plan_modules_plan_position UNIQUE (plan_id, position)
        )
        """
    )
    op.execute(
        "CREATE INDEX suite_plan_modules_plan_idx "
        "ON project_workbench.suite_plan_modules(plan_id, position)"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches "
        "ADD COLUMN kind varchar(20) NOT NULL DEFAULT 'hero'"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches "
        "ADD COLUMN source_plan_id uuid"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches "
        "ADD CONSTRAINT generation_batches_kind_check CHECK (kind IN ('hero', 'suite'))"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches "
        "ADD CONSTRAINT generation_batches_source_plan_fk FOREIGN KEY (source_plan_id) "
        "REFERENCES project_workbench.suite_plans(id) ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches "
        "ADD CONSTRAINT uq_generation_batches_source_plan UNIQUE (source_plan_id)"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_module_tasks ADD COLUMN position integer"
    )
    op.execute(
        """
        WITH ranked AS (
          SELECT id, row_number() OVER (
            PARTITION BY batch_id ORDER BY created_at, id
          ) AS resolved_position
          FROM project_workbench.generation_module_tasks
        )
        UPDATE project_workbench.generation_module_tasks AS module
        SET position = ranked.resolved_position
        FROM ranked
        WHERE module.id = ranked.id
        """
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_module_tasks "
        "ALTER COLUMN position SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_module_tasks "
        "ADD CONSTRAINT generation_module_tasks_position_check CHECK (position > 0)"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_module_tasks "
        "ADD CONSTRAINT uq_generation_module_tasks_batch_position UNIQUE (batch_id, position)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE project_workbench.generation_module_tasks "
        "DROP CONSTRAINT IF EXISTS uq_generation_module_tasks_batch_position"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_module_tasks "
        "DROP CONSTRAINT IF EXISTS generation_module_tasks_position_check"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_module_tasks DROP COLUMN IF EXISTS position"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches "
        "DROP CONSTRAINT IF EXISTS uq_generation_batches_source_plan"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches "
        "DROP CONSTRAINT IF EXISTS generation_batches_source_plan_fk"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches "
        "DROP CONSTRAINT IF EXISTS generation_batches_kind_check"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches DROP COLUMN IF EXISTS source_plan_id"
    )
    op.execute(
        "ALTER TABLE project_workbench.generation_batches DROP COLUMN IF EXISTS kind"
    )
    op.execute("DROP TABLE IF EXISTS project_workbench.suite_plan_modules")
    op.execute("DROP TABLE IF EXISTS project_workbench.suite_plans")
