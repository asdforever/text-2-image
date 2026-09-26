"""显式启用的本机数据库验证：所有写入均在外层事务中回滚。"""
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.canvas_generation_repository import PostgresCanvasGenerationRepository
from backend.app.core.config import Settings
from backend.app.db import create_engine
from backend.app.project_repository import PostgresProjectRepository


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("PICAGENT_CANVAS_DB_CHECK") != "1", reason="显式设置 PICAGENT_CANVAS_DB_CHECK=1 才连接本机数据库，写入全部回滚")
async def test_postgres_versions_persist_between_repository_instances_and_rollback_failed_actions():
    settings = Settings()
    assert settings.database_url
    engine = create_engine(settings.database_url)
    workspace_id = uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("INSERT INTO suite_workbench.workspaces (id, name) VALUES (:id, :name)"), {"id": workspace_id, "name": "画布事务回滚验证"})
                sessions = async_sessionmaker(connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
                project = await PostgresProjectRepository(sessions).create_project("画布临时验证", workspace_id)
                repository = PostgresCanvasGenerationRepository(sessions)
                initial = {"stepId": "step", "currentAssetIds": ["original"], "revisions": []}
                def append(state):
                    state["revisions"].append({"id": "v2", "status": "queued"})
                    return state
                await repository.change(project.id, workspace_id, "step", initial, append)
                reopened = PostgresCanvasGenerationRepository(sessions)
                assert (await reopened.list(project.id, workspace_id))[0]["revisions"][0]["id"] == "v2"
                def broken(state):
                    state["currentAssetIds"] = ["should-not-save"]
                    raise ValueError("回滚")
                with pytest.raises(ValueError):
                    await reopened.change(project.id, workspace_id, "step", None, broken)
                assert (await reopened.list(project.id, workspace_id))[0]["currentAssetIds"] == ["original"]
                assert await reopened.list(project.id, uuid4()) == []
            finally:
                await transaction.rollback()
        async with engine.connect() as check:
            assert await check.scalar(text("SELECT count(*) FROM suite_workbench.workspaces WHERE id=:id"), {"id": workspace_id}) == 0
    finally:
        await engine.dispose()
