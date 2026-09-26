"""add reverse projects

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-09-25
"""

from alembic import op


revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE project_workbench.reverse_projects (
            id uuid PRIMARY KEY,
            workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE CASCADE,
            name text NOT NULL,
            category text NOT NULL DEFAULT '',
            summary text NOT NULL DEFAULT '',
            suitable_for text NOT NULL DEFAULT '',
            goal text NOT NULL DEFAULT '',
            required_materials text NOT NULL DEFAULT '',
            not_suitable_for text NOT NULL DEFAULT '',
            overall jsonb NOT NULL DEFAULT '{}'::jsonb,
            modules jsonb NOT NULL DEFAULT '[]'::jsonb,
            analysis_status text NOT NULL DEFAULT 'idle'
                CHECK (analysis_status IN ('idle', 'running', 'completed', 'failed')),
            analysis_error text,
            revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
            latest_version_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        CREATE INDEX reverse_projects_workspace_updated_idx
            ON project_workbench.reverse_projects(workspace_id, updated_at DESC)
    """)

    op.execute("""
        CREATE TABLE project_workbench.reverse_project_references (
            id uuid PRIMARY KEY,
            workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE CASCADE,
            reverse_project_id uuid NOT NULL
                REFERENCES project_workbench.reverse_projects(id) ON DELETE CASCADE,
            ordinal integer NOT NULL CHECK (ordinal > 0),
            filename text NOT NULL,
            width integer NOT NULL CHECK (width > 0),
            height integer NOT NULL CHECK (height > 0),
            mime_type text NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png', 'image/webp')),
            storage_key text NOT NULL UNIQUE,
            sha256 char(64) NOT NULL,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX reverse_project_references_active_ordinal_uq
            ON project_workbench.reverse_project_references(reverse_project_id, ordinal)
            WHERE active
    """)

    op.execute("""
        CREATE TABLE project_workbench.reverse_versions (
            id uuid PRIMARY KEY,
            workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE CASCADE,
            reverse_project_id uuid NOT NULL
                REFERENCES project_workbench.reverse_projects(id) ON DELETE CASCADE,
            version_no integer NOT NULL CHECK (version_no > 0),
            revision integer NOT NULL CHECK (revision > 0),
            document jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (reverse_project_id, version_no),
            UNIQUE (reverse_project_id, revision)
        )
    """)
    op.execute("""
        ALTER TABLE project_workbench.reverse_projects
            ADD CONSTRAINT reverse_projects_latest_version_fk
            FOREIGN KEY (latest_version_id)
            REFERENCES project_workbench.reverse_versions(id) ON DELETE SET NULL
    """)

    op.execute("""
        CREATE TABLE project_workbench.reverse_bindings (
            id uuid PRIMARY KEY,
            workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
            reverse_project_id uuid NOT NULL
                REFERENCES project_workbench.reverse_projects(id) ON DELETE CASCADE,
            version_id uuid NOT NULL
                REFERENCES project_workbench.reverse_versions(id) ON DELETE RESTRICT,
            target text NOT NULL CHECK (target IN ('hero', 'suite')),
            scope text NOT NULL CHECK (scope IN ('overall', 'module')),
            target_module_id text,
            source_module_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (
                (scope = 'overall' AND target_module_id IS NULL AND source_module_id IS NULL)
                OR
                (scope = 'module' AND target_module_id IS NOT NULL AND source_module_id IS NOT NULL)
            )
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX reverse_bindings_target_slot_uq
            ON project_workbench.reverse_bindings(
                workspace_id, project_id, target, scope, COALESCE(target_module_id, '')
            )
    """)
    op.execute("""
        CREATE INDEX reverse_bindings_reverse_project_idx
            ON project_workbench.reverse_bindings(workspace_id, reverse_project_id, created_at);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS project_workbench.reverse_bindings_reverse_project_idx")
    op.execute("DROP INDEX IF EXISTS project_workbench.reverse_bindings_target_slot_uq")
    op.execute("DROP TABLE IF EXISTS project_workbench.reverse_bindings")
    op.execute("""
        ALTER TABLE project_workbench.reverse_projects
            DROP CONSTRAINT IF EXISTS reverse_projects_latest_version_fk;
    """)
    op.execute("DROP TABLE IF EXISTS project_workbench.reverse_versions")
    op.execute("DROP INDEX IF EXISTS project_workbench.reverse_project_references_active_ordinal_uq")
    op.execute("DROP TABLE IF EXISTS project_workbench.reverse_project_references")
    op.execute("DROP INDEX IF EXISTS project_workbench.reverse_projects_workspace_updated_idx")
    op.execute("DROP TABLE IF EXISTS project_workbench.reverse_projects")
