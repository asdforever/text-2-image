"""Opt-in local database checks; all fixtures are rolled back, no model calls."""
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.config import Settings
from backend.app.db import create_engine
from backend.app.module_planning_repository import PostgresModulePlanningRepository
from backend.app.suite_planning_repository import PostgresSuitePlanningRepository, SuitePlanModuleInput


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("PICAGENT_MODULE_PLAN_DB_CHECK") != "1", reason="Explicitly enable rollback database check")
@pytest.mark.parametrize("module_count", [6, 101])
async def test_master_survives_repository_restart_and_large_suite_can_be_reordered(module_count):
    engine = create_engine(Settings().database_url)
    workspace, project = uuid4(), uuid4()
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("INSERT INTO suite_workbench.workspaces(id,name) VALUES (:id,'planning rollback test')"), {"id": workspace})
                await connection.execute(text("INSERT INTO project_workbench.projects(id,workspace_id,name) VALUES (:id,:workspace,'planning rollback test')"), {"id": project, "workspace": workspace})
                sessions = async_sessionmaker(connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
                repo = PostgresModulePlanningRepository(sessions)
                value, owner = await repo.create(workspace, project, "plan", "a" * 64,
                    {"mode": "suite", "status": "planning", "input": {"brief": "Original brief"}})
                assert owner
                value.update(snapshot={"prompt": "frozen"})
                await repo.save(workspace, project, UUID(value["id"]), value)
                restarted = PostgresModulePlanningRepository(sessions)
                recovered = await restarted.latest(workspace, project, "suite")
                assert recovered["snapshot"] == {"prompt": "frozen"}
                assert await restarted.latest(workspace, project, "hero") is None
                assert await restarted.get(workspace, uuid4(), UUID(value["id"])) is None
                replay, owner = await restarted.create(workspace, project, "plan", "a" * 64, value)
                assert not owner and replay["id"] == value["id"]
                value["createdAt"] = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
                await repo.save(workspace, project, UUID(value["id"]), value)
                assert (await restarted.latest(workspace, project, "suite"))["status"] == "failed"
                value["status"] = "completed"
                assert (await repo.save(workspace, project, UUID(value["id"]), value))["status"] == "failed"

                suites = PostgresSuitePlanningRepository(sessions)
                plan, duplicate = await suites.create_compiling(workspace, project, "six", "b" * 64, {}, [
                    SuitePlanModuleInput(f"module-{i}", i, 1, f"Module {i}", [], {}) for i in range(1, module_count + 1)
                ])
                assert not duplicate
                detail = await suites.get_plan_detail(plan.id, workspace, project)
                assert len(detail.modules) == module_count
                assert detail.plan.requested_module_count == module_count
                await connection.execute(text("UPDATE project_workbench.suite_plans SET status='awaiting_confirmation' WHERE id=:id"), {"id": plan.id})
                order = [m.id for m in reversed(detail.modules)]
                reordered = await suites.reorder_modules(plan.id, workspace, project,
                    expected_plan_revision=plan.revision, ordered_module_ids=order)
                assert [m.id for m in reordered.modules] == order
                assert [m.position for m in reordered.modules] == list(range(1, module_count + 1))
            finally:
                await transaction.rollback()
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT count(*) FROM suite_workbench.workspaces WHERE id=:id"), {"id": workspace}) == 0
    finally:
        await engine.dispose()
