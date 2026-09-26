"""fix protect_prompt_version trigger remove stage field

Revision ID: 3af2e3c6054f
Revises: b5467b039772
Create Date: 2026-09-16 14:20:29.354581
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3af2e3c6054f'
down_revision: Union[str, None] = 'b5467b039772'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop and recreate the trigger function without the stage field
    op.execute("""
        CREATE OR REPLACE FUNCTION prompt_library.protect_prompt_version()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          -- Allow DELETE operations (needed for template cascade deletion)
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;

          -- Block UPDATE operations that change immutable fields (removed stage)
          IF OLD.name IS DISTINCT FROM NEW.name OR OLD.kind IS DISTINCT FROM NEW.kind
             OR OLD.execution_target IS DISTINCT FROM NEW.execution_target
             OR OLD.body IS DISTINCT FROM NEW.body OR OLD.user_prompt_template IS DISTINCT FROM NEW.user_prompt_template
             OR OLD.input_schema IS DISTINCT FROM NEW.input_schema OR OLD.output_schema IS DISTINCT FROM NEW.output_schema
             OR OLD.applicability IS DISTINCT FROM NEW.applicability OR OLD.content_sha256 IS DISTINCT FROM NEW.content_sha256
             OR OLD.version_no IS DISTINCT FROM NEW.version_no OR OLD.template_id IS DISTINCT FROM NEW.template_id THEN
            RAISE EXCEPTION 'prompt versions are immutable';
          END IF;
          RETURN NEW;
        END $$;
    """)


def downgrade() -> None:
    # Restore the original trigger function with the stage field
    op.execute("""
        CREATE OR REPLACE FUNCTION prompt_library.protect_prompt_version()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          -- Allow DELETE operations (needed for template cascade deletion)
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;

          -- Block UPDATE operations that change immutable fields (with stage)
          IF OLD.name IS DISTINCT FROM NEW.name OR OLD.kind IS DISTINCT FROM NEW.kind
             OR OLD.stage IS DISTINCT FROM NEW.stage OR OLD.execution_target IS DISTINCT FROM NEW.execution_target
             OR OLD.body IS DISTINCT FROM NEW.body OR OLD.user_prompt_template IS DISTINCT FROM NEW.user_prompt_template
             OR OLD.input_schema IS DISTINCT FROM NEW.input_schema OR OLD.output_schema IS DISTINCT FROM NEW.output_schema
             OR OLD.applicability IS DISTINCT FROM NEW.applicability OR OLD.content_sha256 IS DISTINCT FROM NEW.content_sha256
             OR OLD.version_no IS DISTINCT FROM NEW.version_no OR OLD.template_id IS DISTINCT FROM NEW.template_id THEN
            RAISE EXCEPTION 'prompt versions are immutable';
          END IF;
          RETURN NEW;
        END $$;
    """)
