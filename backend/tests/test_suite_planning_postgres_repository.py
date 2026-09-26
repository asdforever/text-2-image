import asyncio
import os
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.app.core.errors import AppError
from backend.app.db import create_engine, create_session_factory
from backend.app.suite_planning_repository import (
    PostgresSuitePlanningRepository,
    SuitePlanModuleCompilation,
    SuitePlanModuleInput,
)


TEST_DATABASE_URL = os.getenv("PICAGENT_MIGRATION_TEST_DATABASE_URL")


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="设置 PICAGENT_MIGRATION_TEST_DATABASE_URL 指向专用 PostgreSQL 测试库",
)
def test_postgres_suite_plan_repository_matches_edit_and_rollback_contract() -> None:
    database_name = urlsplit(TEST_DATABASE_URL or "").path.lstrip("/").lower()
    assert "test" in database_name, "只允许连接数据库名含 test 的专用测试库"

    async def run() -> None:
        engine = create_engine(TEST_DATABASE_URL or "")
        sessions = create_session_factory(engine)
        workspace_id, project_id = uuid4(), uuid4()
        try:
            async with sessions() as session, session.begin():
                await session.execute(
                    text(
                        "INSERT INTO suite_workbench.workspaces (id, name) VALUES (:id, :name)"
                    ),
                    {"id": workspace_id, "name": "详情页规划仓储测试"},
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.projects "
                        "(id, workspace_id, name, status) VALUES (:id, :workspace_id, :name, 'active')"
                    ),
                    {"id": project_id, "workspace_id": workspace_id, "name": "规划测试项目"},
                )

            repository = PostgresSuitePlanningRepository(sessions)
            plan, duplicate = await repository.create_compiling(
                workspace_id,
                project_id,
                "pg-compile",
                "a" * 64,
                {"sourceAssetIds": []},
                [
                    SuitePlanModuleInput("suite-hero", 1, 2, "首屏"),
                    SuitePlanModuleInput("suite-scene", 2, 1, "场景"),
                ],
            )
            replay, replayed = await repository.create_compiling(
                workspace_id,
                project_id,
                "pg-compile",
                "a" * 64,
                {"sourceAssetIds": []},
                [
                    SuitePlanModuleInput("suite-hero", 1, 2, "首屏"),
                    SuitePlanModuleInput("suite-scene", 2, 1, "场景"),
                ],
            )
            await repository.mark_awaiting_confirmation(
                plan.id,
                workspace_id,
                {
                    "suite-hero": SuitePlanModuleCompilation("首屏文案", "首屏画面", "首屏提示词", {}),
                    "suite-scene": SuitePlanModuleCompilation("场景文案", "场景画面", "场景提示词", {}),
                },
            )
            detail = await repository.get_latest(project_id, workspace_id)
            assert detail is not None
            target = detail.modules[1]
            updated = await repository.update_module(
                plan.id,
                target.id,
                workspace_id,
                project_id,
                expected_plan_revision=detail.plan.revision,
                expected_module_revision=target.revision,
                visual_direction="真实书房场景",
                requested_image_count=4,
            )

            assert duplicate is False
            assert replayed is True
            assert replay.id == plan.id
            assert updated.modules[1].visual_direction == "真实书房场景"
            assert updated.modules[1].requested_image_count == 4
            with pytest.raises(AppError) as stale:
                await repository.update_module(
                    plan.id,
                    target.id,
                    workspace_id,
                    project_id,
                    expected_plan_revision=detail.plan.revision,
                    expected_module_revision=target.revision,
                    visual_direction="不应写入",
                )
            assert stale.value.code == "SUITE_PLAN_REVISION_CONFLICT"
            after_conflict = await repository.get_plan_detail(plan.id, workspace_id, project_id)
            assert after_conflict is not None
            assert after_conflict.modules[1].visual_direction == "真实书房场景"
        finally:
            await engine.dispose()

    asyncio.run(run())
