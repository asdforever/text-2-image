"""allow prompt version deletion

Revision ID: f9a8b7c6d5e4
Revises: 03a4b5c6d7e8
Create Date: 2026-09-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f9a8b7c6d5e4'
down_revision: Union[str, None] = '03a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old trigger that blocks DELETE
    op.execute("""
        DROP TRIGGER IF EXISTS protect_prompt_version_update ON prompt_library.prompt_versions;
    """)

    # Update the trigger function to allow DELETE operations
    op.execute("""
        CREATE OR REPLACE FUNCTION prompt_library.protect_prompt_version() RETURNS trigger AS $$
        BEGIN
          -- Allow DELETE operations (needed for template cascade deletion)
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;

          -- Block UPDATE operations that change immutable fields
          IF OLD.name IS DISTINCT FROM NEW.name OR OLD.kind IS DISTINCT FROM NEW.kind
             OR OLD.stage IS DISTINCT FROM NEW.stage OR OLD.execution_target IS DISTINCT FROM NEW.execution_target
             OR OLD.body IS DISTINCT FROM NEW.body OR OLD.user_prompt_template IS DISTINCT FROM NEW.user_prompt_template
             OR OLD.input_schema IS DISTINCT FROM NEW.input_schema OR OLD.output_schema IS DISTINCT FROM NEW.output_schema
             OR OLD.applicability IS DISTINCT FROM NEW.applicability OR OLD.content_sha256 IS DISTINCT FROM NEW.content_sha256
             OR OLD.version_no IS DISTINCT FROM NEW.version_no OR OLD.template_id IS DISTINCT FROM NEW.template_id THEN
            RAISE EXCEPTION 'prompt versions are immutable';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql;
    """)

    # Recreate the trigger to only fire on UPDATE (not DELETE)
    op.execute("""
        CREATE TRIGGER protect_prompt_version_update
        BEFORE UPDATE ON prompt_library.prompt_versions
        FOR EACH ROW EXECUTE FUNCTION prompt_library.protect_prompt_version();
    """)


def downgrade() -> None:
    # Restore the old trigger behavior that blocks both UPDATE and DELETE
    op.execute("""
        DROP TRIGGER IF EXISTS protect_prompt_version_update ON prompt_library.prompt_versions;
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
        END $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER protect_prompt_version_update
        BEFORE UPDATE OR DELETE ON prompt_library.prompt_versions
        FOR EACH ROW EXECUTE FUNCTION prompt_library.protect_prompt_version();
    """)
