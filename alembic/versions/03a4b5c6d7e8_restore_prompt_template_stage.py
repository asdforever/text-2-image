"""恢复提示词模板的使用阶段字段。"""

from alembic import op


revision = "03a4b5c6d7e8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE prompt_library.prompt_templates
        ADD COLUMN IF NOT EXISTS stage varchar(30)
        """
    )
    op.execute(
        """
        UPDATE prompt_library.prompt_templates
        SET stage = CASE
          WHEN kind = 'image_to_text' THEN 'reverse_prompt'
          WHEN kind IN ('image_to_image', 'text_to_image') THEN 'task_image'
          ELSE 'plan'
        END
        WHERE stage IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE prompt_library.prompt_templates
        ALTER COLUMN stage SET DEFAULT 'plan',
        ALTER COLUMN stage SET NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE prompt_library.prompt_templates
        DROP COLUMN IF EXISTS stage
        """
    )
