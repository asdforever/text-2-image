"""新增批次生成编排模型。"""

from alembic import op


revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_workbench.generation_batches (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          source_asset_id uuid NOT NULL
            REFERENCES project_workbench.project_assets(id) ON DELETE RESTRICT,
          status varchar(30) NOT NULL DEFAULT 'compiling_prompt',
          compile_idempotency_key varchar(200) NOT NULL,
          compile_fingerprint char(64) NOT NULL,
          confirm_idempotency_key varchar(200),
          confirm_fingerprint char(64),
          snapshot jsonb NOT NULL,
          error_code varchar(80),
          error_message text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          confirmed_at timestamptz,
          completed_at timestamptz,
          CONSTRAINT generation_batches_status_check CHECK (
            status IN (
              'compiling_prompt', 'awaiting_confirmation', 'queued', 'running', 'succeeded',
              'partially_failed', 'failed', 'cancel_requested', 'cancelled'
            )
          ),
          CONSTRAINT uq_generation_batches_compile_idempotency
            UNIQUE (workspace_id, compile_idempotency_key),
          CONSTRAINT uq_generation_batches_confirm_idempotency
            UNIQUE (workspace_id, confirm_idempotency_key),
          CONSTRAINT generation_batches_compile_fingerprint_check
            CHECK (compile_fingerprint ~ '^[0-9a-f]{64}$'),
          CONSTRAINT generation_batches_confirm_fingerprint_check
            CHECK (confirm_fingerprint IS NULL OR confirm_fingerprint ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX generation_batches_project_status_idx "
        "ON project_workbench.generation_batches(project_id, status, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE project_workbench.generation_module_tasks (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          batch_id uuid NOT NULL REFERENCES project_workbench.generation_batches(id) ON DELETE CASCADE,
          module_key varchar(120) NOT NULL,
          requested_image_count integer NOT NULL,
          snapshot jsonb NOT NULL,
          compiled_task_prompt text,
          compiler_output jsonb,
          confirmed_task_prompt text,
          final_prompt text,
          final_prompt_sha256 char(64),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          confirmed_at timestamptz,
          CONSTRAINT generation_module_tasks_requested_image_count_check
            CHECK (requested_image_count BETWEEN 1 AND 4),
          CONSTRAINT uq_generation_module_tasks_batch_module UNIQUE (batch_id, module_key),
          CONSTRAINT generation_module_tasks_final_prompt_sha256_check
            CHECK (final_prompt_sha256 IS NULL OR final_prompt_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX generation_module_tasks_batch_idx "
        "ON project_workbench.generation_module_tasks(batch_id)"
    )
    op.execute(
        """
        CREATE TABLE project_workbench.generation_image_slots (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          batch_id uuid NOT NULL REFERENCES project_workbench.generation_batches(id) ON DELETE CASCADE,
          module_task_id uuid NOT NULL
            REFERENCES project_workbench.generation_module_tasks(id) ON DELETE CASCADE,
          ordinal integer NOT NULL,
          status varchar(30) NOT NULL DEFAULT 'queued',
          generated_asset_id uuid
            REFERENCES project_workbench.project_assets(id) ON DELETE SET NULL,
          lease_token uuid,
          lease_expires_at timestamptz,
          provider_idempotency_key varchar(200),
          error_code varchar(80),
          error_message text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          dispatched_at timestamptz,
          completed_at timestamptz,
          CONSTRAINT generation_image_slots_status_check CHECK (
            status IN (
              'queued', 'leased', 'dispatching', 'succeeded', 'failed',
              'cancel_requested', 'cancelled', 'needs_retry'
            )
          ),
          CONSTRAINT generation_image_slots_ordinal_check CHECK (ordinal > 0),
          CONSTRAINT uq_generation_image_slots_module_ordinal UNIQUE (module_task_id, ordinal)
        )
        """
    )
    op.execute(
        "CREATE INDEX generation_image_slots_queue_idx "
        "ON project_workbench.generation_image_slots(status, lease_expires_at, created_at)"
    )
    op.execute(
        "CREATE INDEX generation_image_slots_batch_idx "
        "ON project_workbench.generation_image_slots(batch_id)"
    )
    op.execute(
        """
        CREATE TABLE project_workbench.generation_slot_attempts (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          slot_id uuid NOT NULL REFERENCES project_workbench.generation_image_slots(id) ON DELETE CASCADE,
          attempt_no integer NOT NULL,
          status varchar(30) NOT NULL DEFAULT 'leased',
          lease_token uuid NOT NULL,
          worker_id varchar(120),
          provider_request_summary jsonb,
          error_code varchar(80),
          error_message text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          dispatched_at timestamptz,
          completed_at timestamptz,
          CONSTRAINT generation_slot_attempts_status_check CHECK (
            status IN ('leased', 'dispatching', 'succeeded', 'failed', 'cancelled', 'needs_retry')
          ),
          CONSTRAINT generation_slot_attempts_attempt_no_check CHECK (attempt_no > 0),
          CONSTRAINT uq_generation_slot_attempts_slot_attempt UNIQUE (slot_id, attempt_no)
        )
        """
    )
    op.execute(
        "CREATE INDEX generation_slot_attempts_slot_idx "
        "ON project_workbench.generation_slot_attempts(slot_id, attempt_no DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_workbench.generation_slot_attempts")
    op.execute("DROP TABLE IF EXISTS project_workbench.generation_image_slots")
    op.execute("DROP TABLE IF EXISTS project_workbench.generation_module_tasks")
    op.execute("DROP TABLE IF EXISTS project_workbench.generation_batches")
