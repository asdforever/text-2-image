"""扩展幂等记录，保存请求指纹、状态和序列化响应。"""

from alembic import op


revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 现有表已经使用 PRIMARY KEY (scope, key)，本迁移保留该唯一作用域。
    op.execute(
        """
        ALTER TABLE suite_workbench.idempotency_keys
          ADD COLUMN request_fingerprint char(64) NOT NULL DEFAULT repeat('0', 64),
          ADD COLUMN status varchar(20) NOT NULL DEFAULT 'completed',
          ADD COLUMN response_status integer,
          ADD COLUMN response_body jsonb,
          ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now(),
          ALTER COLUMN resource_id DROP NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE suite_workbench.idempotency_keys
          ADD CONSTRAINT idempotency_status_check
            CHECK (status IN ('in_progress', 'completed', 'failed')),
          ADD CONSTRAINT idempotency_fingerprint_check
            CHECK (request_fingerprint ~ '^[0-9a-f]{64}$')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM suite_workbench.idempotency_keys WHERE resource_id IS NULL;
        ALTER TABLE suite_workbench.idempotency_keys
          DROP CONSTRAINT idempotency_fingerprint_check,
          DROP CONSTRAINT idempotency_status_check,
          ALTER COLUMN resource_id SET NOT NULL,
          DROP COLUMN updated_at,
          DROP COLUMN response_body,
          DROP COLUMN response_status,
          DROP COLUMN status,
          DROP COLUMN request_fingerprint
        """
    )
