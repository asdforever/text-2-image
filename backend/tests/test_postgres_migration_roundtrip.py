import asyncio
import os
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config


TEST_DATABASE_URL = os.getenv("PICAGENT_MIGRATION_TEST_DATABASE_URL")


def _dsn() -> str:
    value = TEST_DATABASE_URL or ""
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="设置 PICAGENT_MIGRATION_TEST_DATABASE_URL 指向专用 PostgreSQL 测试库",
)
def test_upgrade_downgrade_preserves_suite_and_input_image_data() -> None:
    database_name = urlsplit(_dsn()).path.lstrip("/").lower()
    assert "test" in database_name, "只允许在数据库名含 test 的专用库执行回滚测试"

    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url", (TEST_DATABASE_URL or "").replace("%", "%%")
    )
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    suite_id = uuid4()
    image_id = uuid4()

    async def seed_and_read() -> tuple[int, int]:
        connection = await asyncpg.connect(_dsn())
        try:
            await connection.execute(
                "INSERT INTO suite_workbench.suites "
                "(id,workspace_id,name,status) VALUES ($1,$2,$3,'draft')",
                suite_id,
                UUID("22222222-2222-4222-8222-222222222222"),
                "迁移回滚测试",
            )
            await connection.execute(
                "INSERT INTO suite_workbench.input_images "
                "(id,suite_id,ordinal,original_object_key,thumbnail_object_key,sha256,"
                "width,height,mime_type,original_filename) "
                "VALUES ($1,$2,1,'test/original','test/thumbnail',$3,10,10,'image/png','test.png')",
                image_id,
                suite_id,
                "a" * 64,
            )
            return (
                await connection.fetchval(
                    "SELECT count(*) FROM suite_workbench.suites WHERE id=$1", suite_id
                ),
                await connection.fetchval(
                    "SELECT count(*) FROM suite_workbench.input_images WHERE id=$1", image_id
                ),
            )
        finally:
            await connection.close()

    assert asyncio.run(seed_and_read()) == (1, 1)
    command.downgrade(config, "b7c2e4d91a6f")

    async def counts() -> tuple[int, int]:
        connection = await asyncpg.connect(_dsn())
        try:
            return (
                await connection.fetchval(
                    "SELECT count(*) FROM suite_workbench.suites WHERE id=$1", suite_id
                ),
                await connection.fetchval(
                    "SELECT count(*) FROM suite_workbench.input_images WHERE id=$1", image_id
                ),
            )
        finally:
            await connection.close()

    assert asyncio.run(counts()) == (1, 1)
    command.upgrade(config, "head")
    assert asyncio.run(counts()) == (1, 1)
