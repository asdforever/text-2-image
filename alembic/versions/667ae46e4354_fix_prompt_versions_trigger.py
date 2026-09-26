"""fix_prompt_versions_trigger

Revision ID: 667ae46e4354
Revises: 0172a5ad043e
Create Date: 2026-09-10 14:47:06.545243
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '667ae46e4354'
down_revision: Union[str, None] = '0172a5ad043e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Recreate the protect_prompt_version function without the 'stage' field reference
    op.execute("""
        CREATE OR REPLACE FUNCTION prompt_library.protect_prompt_version() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'prompt versions are immutable'; END IF;
          IF OLD.name IS DISTINCT FROM NEW.name OR OLD.kind IS DISTINCT FROM NEW.kind
             OR OLD.execution_target IS DISTINCT FROM NEW.execution_target
             OR OLD.body IS DISTINCT FROM NEW.body OR OLD.user_prompt_template IS DISTINCT FROM NEW.user_prompt_template
             OR OLD.input_schema IS DISTINCT FROM NEW.input_schema OR OLD.output_schema IS DISTINCT FROM NEW.output_schema
             OR OLD.applicability IS DISTINCT FROM NEW.applicability OR OLD.content_sha256 IS DISTINCT FROM NEW.content_sha256
             OR OLD.version_no IS DISTINCT FROM NEW.version_no OR OLD.template_id IS DISTINCT FROM NEW.template_id THEN
            RAISE EXCEPTION 'prompt versions are immutable';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql
    """)


def downgrade() -> None:
    # Restore the old function with 'stage' field (only if downgrading and stage column exists)
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
