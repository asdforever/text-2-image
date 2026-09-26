"""Create the FastAPI baseline and prompt version tables."""

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SCHEMA IF NOT EXISTS suite_workbench")
    op.execute("CREATE SCHEMA IF NOT EXISTS prompt_library")
    op.execute("""
        CREATE TABLE IF NOT EXISTS suite_workbench.idempotency_keys (
          scope text NOT NULL, key text NOT NULL, resource_id uuid NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (scope, key)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS suite_workbench.suites (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL,
          status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','in_progress')),
          created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS suite_workbench.input_images (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), suite_id uuid NOT NULL REFERENCES suite_workbench.suites(id) ON DELETE CASCADE,
          ordinal integer NOT NULL, original_object_key text NOT NULL, thumbnail_object_key text NOT NULL,
          sha256 char(64) NOT NULL, width integer NOT NULL, height integer NOT NULL, mime_type text NOT NULL,
          original_filename text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
          UNIQUE (suite_id, ordinal), UNIQUE (suite_id, sha256)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS prompt_library.prompt_templates (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(), code varchar(160) NOT NULL UNIQUE,
          name varchar(200) NOT NULL, kind varchar(30) NOT NULL,
          stage varchar(30) NOT NULL, execution_target varchar(30) NOT NULL,
          default_version_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS prompt_library.prompt_versions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          template_id uuid NOT NULL REFERENCES prompt_library.prompt_templates(id) ON DELETE CASCADE,
          version_no integer NOT NULL CHECK (version_no > 0),
          name varchar(200) NOT NULL, kind varchar(30) NOT NULL,
          stage varchar(30) NOT NULL, execution_target varchar(30) NOT NULL,
          body text NOT NULL,
          user_prompt_template text NOT NULL DEFAULT '', input_schema jsonb NOT NULL DEFAULT '[]'::jsonb,
          output_schema jsonb NOT NULL DEFAULT '{}'::jsonb, applicability jsonb NOT NULL DEFAULT '{}'::jsonb,
          content_sha256 char(64) NOT NULL, source varchar(30) NOT NULL,
          change_note text, created_by varchar(120) NOT NULL DEFAULT 'local-user', file_path text NOT NULL,
          file_sync_status varchar(20) NOT NULL DEFAULT 'pending', file_sync_error text,
          created_at timestamptz NOT NULL DEFAULT now(), synced_at timestamptz,
          UNIQUE (template_id, version_no), UNIQUE (template_id, content_sha256)
        )
    """)
    op.execute("""
        ALTER TABLE prompt_library.prompt_templates
          ADD CONSTRAINT prompt_templates_default_version_fk
          FOREIGN KEY (default_version_id) REFERENCES prompt_library.prompt_versions(id)
          DEFERRABLE INITIALLY DEFERRED
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS prompt_versions_template_idx ON prompt_library.prompt_versions(template_id, version_no DESC);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS prompt_versions_sync_idx ON prompt_library.prompt_versions(file_sync_status);
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION prompt_library.protect_prompt_version() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'prompt versions are immutable'; END IF;
          IF OLD.name IS DISTINCT FROM NEW.name OR OLD.kind IS DISTINCT FROM NEW.kind
             OR OLD.stage IS DISTINCT FROM NEW.stage OR OLD.execution_target IS DISTINCT FROM NEW.execution_target
             OR OLD.body IS DISTINCT FROM NEW.body OR OLD.user_prompt_template IS DISTINCT FROM NEW.user_prompt_template
             OR OLD.input_schema IS DISTINCT FROM NEW.input_schema OR OLD.output_schema IS DISTINCT FROM NEW.output_schema
             OR OLD.applicability IS DISTINCT FROM NEW.applicability OR OLD.content_sha256 IS DISTINCT FROM NEW.content_sha256
             OR OLD.version_no IS DISTINCT FROM NEW.version_no OR OLD.template_id IS DISTINCT FROM NEW.template_id THEN
            RAISE EXCEPTION 'prompt versions are immutable';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS protect_prompt_version_update ON prompt_library.prompt_versions;
    """)
    op.execute("""
        CREATE TRIGGER protect_prompt_version_update BEFORE UPDATE OR DELETE ON prompt_library.prompt_versions
          FOR EACH ROW EXECUTE FUNCTION prompt_library.protect_prompt_version()
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS prompt_library CASCADE")
    op.execute("DROP SCHEMA IF EXISTS suite_workbench CASCADE")
