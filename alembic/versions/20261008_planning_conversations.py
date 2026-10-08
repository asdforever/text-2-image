"""Persist scoped planning conversations without changing existing plans/batches."""
from alembic import op

revision = '20261008_planning_conversations'
down_revision = '20261007_reverse_analysis_token'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE project_workbench.planning_conversations (
        id uuid PRIMARY KEY,
        workspace_id uuid NOT NULL REFERENCES suite_workbench.workspaces(id),
        project_id uuid NOT NULL REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
        mode text NOT NULL CHECK (mode IN ('hero', 'suite')),
        creation_mode text NOT NULL CHECK (creation_mode IN ('regular', 'professional')),
        revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
        document jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (workspace_id, project_id, mode, creation_mode)
    )''')
    op.execute('''CREATE TABLE project_workbench.planning_conversation_turns (
        id uuid PRIMARY KEY,
        session_id uuid NOT NULL REFERENCES project_workbench.planning_conversations(id) ON DELETE CASCADE,
        request_key text NOT NULL,
        fingerprint text NOT NULL,
        status text NOT NULL CHECK (status IN ('generating', 'completed', 'preview', 'failed', 'clarification', 'stale')),
        execution_token uuid NOT NULL,
        document jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (session_id, request_key)
    )''')
    op.execute("CREATE UNIQUE INDEX planning_conversation_one_generating ON project_workbench.planning_conversation_turns(session_id) WHERE status = 'generating'")
    op.execute('''CREATE TABLE project_workbench.planning_conversation_versions (
        id uuid PRIMARY KEY,
        session_id uuid NOT NULL REFERENCES project_workbench.planning_conversations(id) ON DELETE CASCADE,
        plan_id uuid NOT NULL,
        version_number integer NOT NULL CHECK (version_number > 0),
        snapshot jsonb NOT NULL,
        restored_from_version_id uuid REFERENCES project_workbench.planning_conversation_versions(id),
        document jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (session_id, version_number)
    )''')
    op.execute('CREATE INDEX planning_conversation_turns_page ON project_workbench.planning_conversation_turns(session_id, created_at DESC, id DESC)')
    op.execute('CREATE INDEX planning_conversation_versions_page ON project_workbench.planning_conversation_versions(session_id, created_at DESC, id DESC)')


def downgrade():
    op.execute('DROP TABLE project_workbench.planning_conversation_versions')
    op.execute('DROP TABLE project_workbench.planning_conversation_turns')
    op.execute('DROP TABLE project_workbench.planning_conversations')
