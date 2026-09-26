"""增加项目成品档案的资产关系和测试结果幂等约束。"""

from alembic import op


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 唯一索引创建前先归档重复的活动项目产品，保留最早记录及所有历史版本。
    op.execute(
        """
        WITH ranked AS (
          SELECT id,
                 ROW_NUMBER() OVER (
                   PARTITION BY workspace_id, project_id
                   ORDER BY created_at, id
                 ) AS position
          FROM project_workbench.products
          WHERE project_id IS NOT NULL AND archived_at IS NULL
        )
        UPDATE project_workbench.products AS product
        SET archived_at = now(), updated_at = now()
        FROM ranked
        WHERE product.id = ranked.id AND ranked.position > 1
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_products_workspace_project_active
        ON project_workbench.products (workspace_id, project_id)
        WHERE project_id IS NOT NULL AND archived_at IS NULL
        """
    )
    op.execute(
        """
        CREATE TABLE project_workbench.product_asset_links (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workspace_id uuid NOT NULL
            REFERENCES suite_workbench.workspaces(id) ON DELETE RESTRICT,
          project_id uuid NOT NULL
            REFERENCES project_workbench.projects(id) ON DELETE CASCADE,
          product_id uuid NOT NULL
            REFERENCES project_workbench.products(id) ON DELETE CASCADE,
          project_asset_id uuid NOT NULL
            REFERENCES project_workbench.project_assets(id) ON DELETE CASCADE,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_product_asset_links_product_asset
            UNIQUE (product_id, project_asset_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX product_asset_links_project_idx
        ON project_workbench.product_asset_links (workspace_id, project_id, created_at)
        """
    )

    # 历史重复测试成品保留文件，只解除重复任务关联，再建立幂等索引。
    op.execute(
        """
        WITH ranked AS (
          SELECT id,
                 ROW_NUMBER() OVER (
                   PARTITION BY test_run_id
                   ORDER BY created_at, id
                 ) AS position
          FROM prompt_library.products
          WHERE test_run_id IS NOT NULL
        )
        UPDATE prompt_library.products AS product
        SET test_run_id = NULL
        FROM ranked
        WHERE product.id = ranked.id AND ranked.position > 1
        """
    )
    op.execute("DROP INDEX IF EXISTS prompt_library.products_test_run_idx")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_products_test_run
        ON prompt_library.products (test_run_id)
        WHERE test_run_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS prompt_library.uq_prompt_products_test_run")
    op.execute(
        "CREATE INDEX IF NOT EXISTS products_test_run_idx "
        "ON prompt_library.products (test_run_id)"
    )
    op.execute("DROP TABLE IF EXISTS project_workbench.product_asset_links")
    op.execute(
        "DROP INDEX IF EXISTS project_workbench.uq_products_workspace_project_active"
    )
