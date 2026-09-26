"""新增图像感知主图生成任务。"""

from alembic import op


revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE project_workbench.hero_generation_tasks (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id),
          project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          source_asset_id uuid NOT NULL
            REFERENCES project_workbench.project_assets(id) ON DELETE RESTRICT,
          status varchar(30) NOT NULL DEFAULT 'compiling_prompt',
          compile_idempotency_key varchar(200) NOT NULL,
          compile_fingerprint char(64) NOT NULL,
          confirm_idempotency_key varchar(200),
          confirm_fingerprint char(64),
          snapshot jsonb NOT NULL,
          compiled_task_prompt text,
          compiler_output jsonb,
          confirmed_task_prompt text,
          final_prompt text,
          final_prompt_sha256 char(64),
          provider_request jsonb,
          generated_asset_id uuid
            REFERENCES project_workbench.project_assets(id) ON DELETE SET NULL,
          error_code varchar(80),
          error_message text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          confirmed_at timestamptz,
          completed_at timestamptz,
          CONSTRAINT hero_generation_tasks_status_check CHECK (
            status IN (
              'compiling_prompt', 'awaiting_confirmation', 'generating', 'succeeded', 'failed'
            )
          ),
          CONSTRAINT uq_hero_generation_compile_idempotency
            UNIQUE (workspace_id, compile_idempotency_key),
          CONSTRAINT uq_hero_generation_confirm_idempotency
            UNIQUE (workspace_id, confirm_idempotency_key),
          CONSTRAINT hero_generation_compile_fingerprint_check
            CHECK (compile_fingerprint ~ '^[0-9a-f]{64}$'),
          CONSTRAINT hero_generation_confirm_fingerprint_check
            CHECK (confirm_fingerprint IS NULL OR confirm_fingerprint ~ '^[0-9a-f]{64}$'),
          CONSTRAINT hero_generation_final_prompt_sha256_check
            CHECK (final_prompt_sha256 IS NULL OR final_prompt_sha256 ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        "CREATE INDEX hero_generation_tasks_project_status_idx "
        "ON project_workbench.hero_generation_tasks(project_id, status, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX hero_generation_tasks_source_asset_idx "
        "ON project_workbench.hero_generation_tasks(source_asset_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_workbench.hero_generation_tasks")
