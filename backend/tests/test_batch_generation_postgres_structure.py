import asyncio
from datetime import timedelta
from contextlib import asynccontextmanager
import os
from urllib.parse import urlsplit
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text

from backend.app.batch_generation_repository import PostgresBatchGenerationRepository
from backend.app.core.config import get_settings
from backend.app.db import create_engine, create_session_factory


TEST_DATABASE_URL = os.getenv("PICAGENT_MIGRATION_TEST_DATABASE_URL")


@pytest.mark.asyncio
async def test_postgres_claim_query_refills_independent_slots_with_skip_locked() -> None:
    statements = []

    class EmptyRows:
        def mappings(self): return self
        def all(self): return []

    class Session:
        @asynccontextmanager
        async def begin(self): yield

        async def execute(self, query, parameters):
            statements.append((str(query), parameters))
            return EmptyRows()

    @asynccontextmanager
    async def sessions(): yield Session()

    repository = PostgresBatchGenerationRepository(sessions)
    assert await repository.claim_queued_slots("test", limit=2, lease_duration=timedelta(seconds=30)) == []
    query, parameters = statements[0]
    assert parameters["limit"] == 2
    assert "ORDER BY batch.created_at, module.position, slot.ordinal, slot.id" in query
    assert "LIMIT :limit FOR UPDATE OF slot SKIP LOCKED" in query
    assert "NOT EXISTS" not in query


def _dsn() -> str:
    return (TEST_DATABASE_URL or "").replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="设置 PICAGENT_MIGRATION_TEST_DATABASE_URL 指向专用 PostgreSQL 测试库",
)
def test_batch_generation_migration_creates_queue_tables_and_constraints() -> None:
    database_name = urlsplit(_dsn()).path.lstrip("/").lower()
    assert "test" in database_name, "只允许连接数据库名含 test 的专用测试库"

    async def read_structure() -> tuple[set[str], set[str]]:
        connection = await asyncpg.connect(_dsn())
        try:
            tables = {
                row["table_name"]
                for row in await connection.fetch(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'project_workbench' "
                    "AND table_name LIKE 'generation_%'"
                )
            }
            constraints = {
                row["conname"]
                for row in await connection.fetch(
                    "SELECT constraint_name AS conname "
                    "FROM information_schema.table_constraints "
                    "WHERE table_schema = 'project_workbench' "
                    "AND table_name IN ("
                    "'generation_batches', 'generation_module_tasks', "
                    "'generation_image_slots', 'generation_slot_attempts'"
                    ")"
                )
            }
            return tables, constraints
        finally:
            await connection.close()

    tables, constraints = asyncio.run(read_structure())

    assert {
        "generation_batches",
        "generation_module_tasks",
        "generation_image_slots",
        "generation_slot_attempts",
    } <= tables
    assert {
        "generation_batches_status_check",
        "generation_module_tasks_requested_image_count_check",
        "generation_image_slots_status_check",
        "generation_slot_attempts_status_check",
    } <= constraints


@pytest.mark.asyncio
async def test_claim_queued_slot_returns_persisted_lease_and_creates_attempt() -> None:
    """领取槽位必须返回 UPDATE 后的租约，不能读到语句开始时的旧快照。"""
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 PostgreSQL，跳过数据库契约测试")

    engine = create_engine(settings.database_url)
    workspace_id = settings.local_workspace_id
    project_id = uuid4()
    object_id = uuid4()
    asset_id = uuid4()
    batch_id = uuid4()
    module_id = uuid4()
    slot_id = uuid4()

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = create_session_factory(connection)
            async with sessions() as session, session.begin():
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.projects(id, workspace_id, name) "
                        "VALUES (:id, :workspace, '生成队列租约测试')"
                    ),
                    {"id": project_id, "workspace": workspace_id},
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.asset_objects("
                        "id, workspace_id, storage_key, original_filename, media_type, "
                        "byte_size, width, height, sha256) VALUES ("
                        ":id, :workspace, :key, 'source.png', 'image/png', 1, 1, 1, :sha)"
                    ),
                    {
                        "id": object_id,
                        "workspace": workspace_id,
                        "key": f"tests/generation-lease/{object_id}.png",
                        "sha": "a" * 64,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.project_assets("
                        "id, project_id, object_id, kind) "
                        "VALUES (:id, :project, :object, 'source')"
                    ),
                    {"id": asset_id, "project": project_id, "object": object_id},
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.generation_batches("
                        "id, workspace_id, project_id, source_asset_id, status, "
                        "compile_idempotency_key, compile_fingerprint, snapshot, kind) VALUES ("
                        ":id, :workspace, :project, :asset, 'queued', :key, :fingerprint, "
                        "CAST('{}' AS jsonb), 'hero')"
                    ),
                    {
                        "id": batch_id,
                        "workspace": workspace_id,
                        "project": project_id,
                        "asset": asset_id,
                        "key": f"test-{batch_id}",
                        "fingerprint": "b" * 64,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.generation_module_tasks("
                        "id, batch_id, module_key, position, requested_image_count, snapshot) "
                        "VALUES (:id, :batch, 'main-image', 1, 1, CAST('{}' AS jsonb))"
                    ),
                    {"id": module_id, "batch": batch_id},
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.generation_image_slots("
                        "id, batch_id, module_task_id, ordinal, created_at, updated_at) "
                        "VALUES (:id, :batch, :module, 1, "
                        "TIMESTAMPTZ '2000-01-01 00:00:00+00', "
                        "TIMESTAMPTZ '2000-01-01 00:00:00+00')"
                    ),
                    {"id": slot_id, "batch": batch_id, "module": module_id},
                )

            repository = PostgresBatchGenerationRepository(sessions)
            claimed = await repository.claim_queued_slots(
                "test-worker", limit=1, lease_duration=timedelta(seconds=30)
            )

            assert len(claimed) == 1
            assert claimed[0].lease_token is not None
            async with sessions() as session:
                attempt_token = await session.scalar(
                    text(
                        "SELECT lease_token FROM project_workbench.generation_slot_attempts "
                        "WHERE slot_id=:slot_id"
                    ),
                    {"slot_id": slot_id},
                )
            assert attempt_token == claimed[0].lease_token
            await transaction.rollback()
    finally:
        await engine.dispose()
