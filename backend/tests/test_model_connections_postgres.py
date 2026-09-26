"""本机真实连接表验证，使用随机工作区及外层事务回滚，不调用模型。"""
import os
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.application.model_connection_service import ModelConnectionService
from backend.app.core.config import Settings
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.db import create_engine
from backend.app.generation_config_catalog import create_default_generation_config
from backend.app.generation_config_repository import PostgresGenerationConfigRepository
from backend.app.model_connection_repository import PostgresModelConnectionRepository


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("PICAGENT_MODEL_CONNECTION_DB_CHECK") != "1", reason="显式启用真实数据库回滚检查")
async def test_connections_and_published_references_survive_service_recreation():
    settings = Settings(model_connection_encryption_key=Fernet.generate_key().decode())
    engine = create_engine(settings.database_url)
    workspace_id = uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("INSERT INTO suite_workbench.workspaces(id,name) VALUES (:id,'模型连接回滚验证')"), {"id": workspace_id})
                sessions = async_sessionmaker(connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
                repository = PostgresModelConnectionRepository(sessions)
                service = ModelConnectionService(repository, identity, settings)
                first = await service.create({"baseUrl": "https://a.example/v1", "modelName": "model-a", "protocol": "openai_images", "apiKey": "db-test-secret"})
                frozen = await service.snapshot({"id": "image-a", "connectionId": first["id"]})
                second = await service.create({"baseUrl": "https://b.example", "modelName": "model-b", "protocol": "openai_images", "reuseConnectionId": first["id"]})
                configs = PostgresGenerationConfigRepository(sessions)
                content = create_default_generation_config()
                content["models"][0]["connectionId"] = second["id"]
                await configs.bootstrap(workspace_id, content)
                persisted = await PostgresGenerationConfigRepository(sessions).get_current(workspace_id)
                assert persisted.content["models"][0]["connectionId"] == second["id"]
                restarted = ModelConnectionService(PostgresModelConnectionRepository(sessions), identity, settings)
                assert (await restarted.resolve(frozen)).model_name == "model-a"
                assert (await restarted.resolve({"connectionId": second["id"]})).api_key == "db-test-secret"
                record = await repository.get(UUID(first["id"]), workspace_id)
                assert b"db-test-secret" not in record.encrypted_key
                assert "db-test-secret" not in str(await restarted.list()) + str(persisted.content)
            finally:
                await transaction.rollback()
        async with engine.connect() as check:
            assert await check.scalar(text("SELECT count(*) FROM suite_workbench.workspaces WHERE id=:id"), {"id": workspace_id}) == 0
            assert await check.scalar(text("SELECT count(*) FROM generation_config.model_connections WHERE workspace_id=:id"), {"id": workspace_id}) == 0
    finally:
        await engine.dispose()
