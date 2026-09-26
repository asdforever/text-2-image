"""Merge the prompt trigger and test-run constraint migration branches.

Revision ID: merge_prompt_asset_heads
Revises: 667ae46e4354, remove_test_runs_unique
"""

from collections.abc import Sequence


revision: str = "merge_prompt_asset_heads"
down_revision: tuple[str, str] = ("667ae46e4354", "remove_test_runs_unique")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
