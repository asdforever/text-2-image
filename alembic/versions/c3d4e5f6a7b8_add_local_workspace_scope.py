"""add local workspace scope to suite records

Revision ID: c3d4e5f6a7b8
Revises: b7c2e4d91a6f
"""

from collections.abc import Sequence

from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b7c2e4d91a6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCAL_WORKSPACE_ID = "22222222-2222-4222-8222-222222222222"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS suite_workbench.workspaces (
          id uuid PRIMARY KEY,
          name text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        INSERT INTO suite_workbench.workspaces (id, name)
        VALUES ('22222222-2222-4222-8222-222222222222', '本地工作区')
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        ALTER TABLE suite_workbench.suites
          ADD COLUMN IF NOT EXISTS workspace_id uuid
        """
    )
    op.execute(
        """
        UPDATE suite_workbench.suites
        SET workspace_id = '22222222-2222-4222-8222-222222222222'
        WHERE workspace_id IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE suite_workbench.suites
          ALTER COLUMN workspace_id SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE suite_workbench.suites
          ADD CONSTRAINT suites_workspace_fk
          FOREIGN KEY (workspace_id) REFERENCES suite_workbench.workspaces(id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS suites_workspace_idx
          ON suite_workbench.suites(workspace_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS suite_workbench.suites_workspace_idx")
    op.execute(
        """
        ALTER TABLE suite_workbench.suites
          DROP CONSTRAINT IF EXISTS suites_workspace_fk
        """
    )
    op.execute(
        """
        ALTER TABLE suite_workbench.suites
          DROP COLUMN IF EXISTS workspace_id
        """
    )
    op.execute("DROP TABLE IF EXISTS suite_workbench.workspaces")
