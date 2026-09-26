"""prompt_workspace_and_asset_library

Revision ID: 0172a5ad043e
Revises: 0001_initial
Create Date: 2026-09-10 10:46:54.302790
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0172a5ad043e'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建 asset_libraries 表
    op.create_table(
        'asset_libraries',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('asset_type', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        schema='prompt_library'
    )

    # 2. 创建 assets 表
    op.create_table(
        'assets',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('library_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('asset_type', sa.String(20), nullable=False),
        sa.Column('minio_bucket', sa.String(100), nullable=True),
        sa.Column('minio_key', sa.String(500), nullable=True),
        sa.Column('file_type', sa.String(50), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['library_id'], ['prompt_library.asset_libraries.id'], ondelete='CASCADE'),
        schema='prompt_library'
    )
    op.create_index('assets_library_idx', 'assets', ['library_id'], schema='prompt_library')
    op.create_index('assets_type_idx', 'assets', ['asset_type'], schema='prompt_library')

    # 3. 创建 product_libraries 表
    op.create_table(
        'product_libraries',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('library_type', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        schema='prompt_library'
    )

    # PLACEHOLDER_FOR_MORE_TABLES

    # 4. 创建 products 表
    op.create_table(
        'products',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('library_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('product_type', sa.String(50), nullable=False),
        sa.Column('minio_bucket', sa.String(100), nullable=False),
        sa.Column('minio_key', sa.String(500), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('test_run_id', sa.UUID(), nullable=True),
        sa.Column('project_id', sa.UUID(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['library_id'], ['prompt_library.product_libraries.id'], ondelete='CASCADE'),
        schema='prompt_library'
    )
    op.create_index('products_library_idx', 'products', ['library_id'], schema='prompt_library')

    # 5. 创建 test_runs 表 (先不加外键，等 products 表创建后再添加)
    op.create_table(
        'test_runs',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('prompt_version_id', sa.UUID(), nullable=False),
        sa.Column('input_asset_id', sa.UUID(), nullable=True),
        sa.Column('input_text', sa.Text(), nullable=True),
        sa.Column('output_product_id', sa.UUID(), nullable=True),
        sa.Column('output_text', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['prompt_version_id'], ['prompt_library.prompt_versions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['input_asset_id'], ['prompt_library.assets.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('prompt_version_id', 'input_asset_id', name='uq_test_runs_version_asset'),
        schema='prompt_library'
    )
    op.create_index('test_runs_version_idx', 'test_runs', ['prompt_version_id'], schema='prompt_library')
    op.create_index('test_runs_asset_idx', 'test_runs', ['input_asset_id'], schema='prompt_library')

    # 现在为 products 表添加 test_run_id 外键
    op.create_index('products_test_run_idx', 'products', ['test_run_id'], schema='prompt_library')
    op.create_foreign_key(
        'fk_products_test_run',
        'products', 'test_runs',
        ['test_run_id'], ['id'],
        source_schema='prompt_library',
        referent_schema='prompt_library',
        ondelete='SET NULL'
    )

    # 6. 为 prompt_templates 添加 kind_name 列 (nullable)
    op.add_column('prompt_templates', sa.Column('kind_name', sa.String(50), nullable=True), schema='prompt_library')

    # PLACEHOLDER_FOR_DATA_MIGRATION

    # 7. 数据迁移：映射现有 kind/stage 到新的 kind 和 kind_name
    # 先查询现有数据以确定映射规则
    op.execute("""
        UPDATE prompt_library.prompt_templates SET
            kind = CASE
                WHEN stage = 'reverse_prompt' THEN 'image_to_text'
                WHEN stage = 'task_image' THEN 'image_to_image'
                WHEN kind = 'direct_generation' AND stage = 'plan' THEN 'text_to_text'
                WHEN kind = 'planner' THEN 'text_to_text'
                ELSE 'text_to_text'
            END,
            kind_name = CASE
                WHEN stage = 'reverse_prompt' THEN '图生文'
                WHEN stage = 'task_image' THEN '图生图'
                WHEN kind = 'direct_generation' AND stage = 'plan' THEN '文生文'
                WHEN kind = 'planner' THEN '文生文'
                ELSE '文生文'
            END
        WHERE kind_name IS NULL
    """)

    # 临时禁用 prompt_versions 的不可变触发器
    op.execute("ALTER TABLE prompt_library.prompt_versions DISABLE TRIGGER protect_prompt_version_update")

    # 同步更新 prompt_versions 表的 kind
    op.execute("""
        UPDATE prompt_library.prompt_versions pv SET
            kind = pt.kind
        FROM prompt_library.prompt_templates pt
        WHERE pv.template_id = pt.id
    """)

    # 重新启用触发器
    op.execute("ALTER TABLE prompt_library.prompt_versions ENABLE TRIGGER protect_prompt_version_update")

    # 8. 删除 stage 列
    op.drop_column('prompt_templates', 'stage', schema='prompt_library')
    op.drop_column('prompt_versions', 'stage', schema='prompt_library')

    # 9. 修改 kind_name 为 NOT NULL
    op.alter_column('prompt_templates', 'kind_name', nullable=False, schema='prompt_library')

    # 10. 重新创建 kind 的 CHECK 约束（如果有的话，否则跳过）
    # 注意：如果原来使用 Enum 类型，需要删除旧的 Enum 类型并创建新的
    # 这里假设使用 String 类型 + CHECK 约束
    op.execute("""
        ALTER TABLE prompt_library.prompt_templates
        DROP CONSTRAINT IF EXISTS ck_prompt_templates_kind
    """)
    op.execute("""
        ALTER TABLE prompt_library.prompt_templates
        ADD CONSTRAINT ck_prompt_templates_kind
        CHECK (kind IN ('image_to_image', 'text_to_image', 'text_to_text', 'image_to_text'))
    """)

    op.execute("""
        ALTER TABLE prompt_library.prompt_versions
        DROP CONSTRAINT IF EXISTS ck_prompt_versions_kind
    """)
    op.execute("""
        ALTER TABLE prompt_library.prompt_versions
        ADD CONSTRAINT ck_prompt_versions_kind
        CHECK (kind IN ('image_to_image', 'text_to_image', 'text_to_text', 'image_to_text'))
    """)


def downgrade() -> None:
    # 回滚顺序与 upgrade 相反

    # 10. 删除 kind 的 CHECK 约束
    op.execute("ALTER TABLE prompt_library.prompt_templates DROP CONSTRAINT IF EXISTS ck_prompt_templates_kind")
    op.execute("ALTER TABLE prompt_library.prompt_versions DROP CONSTRAINT IF EXISTS ck_prompt_versions_kind")

    # 9. 修改 kind_name 为 nullable (准备删除)
    op.alter_column('prompt_templates', 'kind_name', nullable=True, schema='prompt_library')

    # 8. 恢复 stage 列
    op.add_column('prompt_templates', sa.Column('stage', sa.String(30), nullable=True), schema='prompt_library')
    op.add_column('prompt_versions', sa.Column('stage', sa.String(30), nullable=True), schema='prompt_library')

    # 7. 回滚数据迁移 (尝试恢复 stage 值，但可能丢失精度)
    op.execute("""
        UPDATE prompt_library.prompt_templates SET
            stage = CASE
                WHEN kind = 'image_to_text' THEN 'reverse_prompt'
                WHEN kind = 'image_to_image' THEN 'task_image'
                ELSE 'plan'
            END,
            kind = CASE
                WHEN kind = 'image_to_text' THEN 'direct_generation'
                WHEN kind = 'image_to_image' THEN 'direct_generation'
                ELSE 'planner'
            END
    """)

    # 临时禁用 prompt_versions 的不可变触发器
    op.execute("ALTER TABLE prompt_library.prompt_versions DISABLE TRIGGER protect_prompt_version_update")

    op.execute("""
        UPDATE prompt_library.prompt_versions pv SET
            stage = pt.stage,
            kind = pt.kind
        FROM prompt_library.prompt_templates pt
        WHERE pv.template_id = pt.id
    """)

    # 重新启用触发器
    op.execute("ALTER TABLE prompt_library.prompt_versions ENABLE TRIGGER protect_prompt_version_update")

    # 6. 删除 kind_name 列
    op.drop_column('prompt_templates', 'kind_name', schema='prompt_library')

    # 5. 删除 products 的 test_run_id 外键
    op.drop_constraint('fk_products_test_run', 'products', type_='foreignkey', schema='prompt_library')
    op.drop_index('products_test_run_idx', 'products', schema='prompt_library')

    # 删除 test_runs 表
    op.drop_index('test_runs_asset_idx', 'test_runs', schema='prompt_library')
    op.drop_index('test_runs_version_idx', 'test_runs', schema='prompt_library')
    op.drop_table('test_runs', schema='prompt_library')

    # 4. 删除 products 表
    op.drop_index('products_library_idx', 'products', schema='prompt_library')
    op.drop_table('products', schema='prompt_library')

    # 3. 删除 product_libraries 表
    op.drop_table('product_libraries', schema='prompt_library')

    # 2. 删除 assets 表
    op.drop_index('assets_type_idx', 'assets', schema='prompt_library')
    op.drop_index('assets_library_idx', 'assets', schema='prompt_library')
    op.drop_table('assets', schema='prompt_library')

    # 1. 删除 asset_libraries 表
    op.drop_table('asset_libraries', schema='prompt_library')
