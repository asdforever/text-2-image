"""add custom prompt categories

Revision ID: b7c2e4d91a6f
Revises: 16fee5f1491e
Create Date: 2026-09-13 21:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c2e4d91a6f"
down_revision: Union[str, None] = "16fee5f1491e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_categories",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        schema="prompt_library",
    )
    op.create_index(
        "prompt_categories_name_lower_uq",
        "prompt_categories",
        [sa.text("lower(name)")],
        unique=True,
        schema="prompt_library",
    )
    op.add_column(
        "prompt_templates",
        sa.Column("category_id", sa.UUID(), nullable=True),
        schema="prompt_library",
    )
    op.create_foreign_key(
        "prompt_templates_category_fk",
        "prompt_templates",
        "prompt_categories",
        ["category_id"],
        ["id"],
        source_schema="prompt_library",
        referent_schema="prompt_library",
        ondelete="SET NULL",
    )
    op.create_index(
        "prompt_templates_category_idx",
        "prompt_templates",
        ["category_id"],
        schema="prompt_library",
    )


def downgrade() -> None:
    op.drop_index("prompt_templates_category_idx", table_name="prompt_templates", schema="prompt_library")
    op.drop_constraint("prompt_templates_category_fk", "prompt_templates", schema="prompt_library", type_="foreignkey")
    op.drop_column("prompt_templates", "category_id", schema="prompt_library")
    op.drop_index("prompt_categories_name_lower_uq", table_name="prompt_categories", schema="prompt_library")
    op.drop_table("prompt_categories", schema="prompt_library")
