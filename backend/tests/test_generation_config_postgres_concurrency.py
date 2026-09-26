import asyncio
import os
from copy import deepcopy
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from backend.app.application.generation_config_service import GenerationConfigService
from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.ports import SystemClock
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.db import create_engine, create_session_factory
from backend.app.generation_config_catalog import create_default_generation_config
from backend.app.generation_config_repository import PostgresGenerationConfigRepository


TEST_DATABASE_URL = os.getenv("PICAGENT_MIGRATION_TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="设置 PICAGENT_MIGRATION_TEST_DATABASE_URL 指向专用 PostgreSQL 测试库",
)
def test_postgres_generation_config_concurrent_bootstrap_and_publish_are_serialized() -> None:
    database_name = urlsplit(TEST_DATABASE_URL or "").path.lstrip("/").lower()
    assert "test" in database_name, "只允许在数据库名含 test 的专用库执行并发测试"

    async def run() -> None:
        engine = create_engine(TEST_DATABASE_URL or "")
        sessions = create_session_factory(engine)
        workspace_id = uuid4()
        try:
            async with sessions() as session, session.begin():
                await session.execute(
                    text(
                        "INSERT INTO suite_workbench.workspaces (id, name) "
                        "VALUES (:id, :name)"
                    ),
                    {"id": workspace_id, "name": "生成配置并发测试"},
                )
            repository = PostgresGenerationConfigRepository(sessions)
            identity = LocalSingleUserIdentityProvider(
                IdentityContext(workspace_id, workspace_id, "owner")
            )
            service = GenerationConfigService(
                repository, identity, MemoryIdempotencyStore(), SystemClock()
            )

            published, draft = await asyncio.gather(
                service.get_published(), service.get_draft()
            )
            assert published.version_no == 1
            assert draft.base_version_no == 1
            assert [item.version_no for item in await repository.list_versions(workspace_id)] == [1]

            updated_draft = deepcopy(draft.content)
            updated_draft["models"][0]["label"] = "PostgreSQL 并发模型"
            await service.replace_draft(updated_draft, 1)
            first, second = await asyncio.gather(
                service.publish("postgres-publish-a"),
                service.publish("postgres-publish-b"),
            )
            assert {first.version_no, second.version_no} == {2}
            versions = await repository.list_versions(workspace_id)
            assert [item.version_no for item in versions] == [1, 2]
            assert versions[-1].content["version"] == versions[-1].version_no == 2
        finally:
            await engine.dispose()

    asyncio.run(run())
