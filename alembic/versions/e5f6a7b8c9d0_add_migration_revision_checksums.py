"""增加 Alembic revision 文件校验和审计表。"""

from alembic import op


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE suite_workbench.migration_revision_checksums (
          revision varchar(64) PRIMARY KEY,
          checksum char(64) NOT NULL,
          recorded_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT migration_revision_checksum_format
            CHECK (checksum ~ '^[0-9a-f]{64}$')
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE suite_workbench.migration_revision_checksums"
    )
