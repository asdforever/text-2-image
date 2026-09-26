import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.app.core.errors import AppError
from backend.app.db import create_engine, create_session_factory
from backend.app.workbench_repository import (
    PostgresWorkbenchRepository,
    WorkbenchTaskInput,
)


ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv("PICAGENT_MIGRATION_TEST_DATABASE_URL")


def test_postgres_layout_insert_conflict_is_explicitly_rejected() -> None:
    source = (ROOT / "backend" / "app" / "workbench_repository.py").read_text(
        encoding="utf-8"
    )
    insert_marker = "ON CONFLICT (project_id) DO NOTHING RETURNING *"
    insert_start = source.index(insert_marker)
    update_start = source.index("            else:", insert_start)
    insert_block = source[insert_start:update_start]
    assert "WORKBENCH_LAYOUT_CONFLICT" in insert_block
    assert "value = row.mappings().first()" in insert_block
    assert "if value is None" in insert_block


def test_postgres_task_creation_handles_concurrent_plan_item_conflicts() -> None:
    source = (ROOT / "backend" / "app" / "workbench_repository.py").read_text(
        encoding="utf-8"
    )
    task_insert_start = source.index("INSERT INTO project_workbench.workbench_tasks")
    task_insert_end = source.index("            return created, False", task_insert_start)
    task_insert_block = source[task_insert_start:task_insert_end]
    assert "ON CONFLICT (project_id,plan_snapshot_id,plan_item_id) DO NOTHING" in task_insert_block
    assert "saw_conflict" in task_insert_block


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="设置 PICAGENT_MIGRATION_TEST_DATABASE_URL 指向专用 PostgreSQL 测试库",
)
def test_postgres_workbench_contract_rolls_back_stale_writes_and_layout_conflicts() -> None:
    database_name = urlsplit(TEST_DATABASE_URL or "").path.lstrip("/").lower()
    assert "test" in database_name, "只允许连接数据库名含 test 的专用测试库"

    async def run() -> None:
        engine = create_engine(TEST_DATABASE_URL or "")
        sessions = create_session_factory(engine)
        workspace_id, project_id, plan_id = uuid4(), uuid4(), uuid4()
        try:
            async with sessions() as session, session.begin():
                await session.execute(
                    text("INSERT INTO suite_workbench.workspaces (id, name) VALUES (:id, :name)"),
                    {"id": workspace_id, "name": "工作台仓储契约测试"},
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.projects (id, workspace_id, name, status) "
                        "VALUES (:id, :workspace_id, :name, 'active')"
                    ),
                    {"id": project_id, "workspace_id": workspace_id, "name": "契约测试项目"},
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.suite_plans "
                        "(id, workspace_id, project_id, status, revision, requested_module_count, "
                        "compile_idempotency_key, compile_fingerprint, snapshot) "
                        "VALUES (:id, :workspace_id, :project_id, 'confirmed', 1, 1, :key, :fingerprint, '{}'::jsonb)"
                    ),
                    {
                        "id": plan_id,
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "key": f"pg-workbench-{plan_id}",
                        "fingerprint": "a" * 64,
                    },
                )

            repository = PostgresWorkbenchRepository(sessions)
            tasks, replayed = await repository.create_tasks(
                workspace_id,
                project_id,
                plan_id,
                "create-contract",
                [WorkbenchTaskInput(uuid4(), 1, "首屏", "用途", "初始提示词", {"n": 1})],
            )
            assert replayed is False
            task = tasks[0]
            updated = await repository.update_task(
                task.id,
                workspace_id,
                task.prompt_revision,
                {"prompt_draft": "服务端提示词"},
            )
            assert updated.prompt_revision == 2
            with pytest.raises(AppError) as stale:
                await repository.update_task(
                    task.id,
                    workspace_id,
                    task.prompt_revision - 1,
                    {"prompt_draft": "不应写入"},
                )
            assert stale.value.code == "WORKBENCH_TASK_REVISION_CONFLICT"
            persisted = await repository.get_task(task.id, workspace_id)
            assert persisted is not None
            assert persisted.prompt_draft == "服务端提示词"
            assert persisted.prompt_revision == 2

            first_layout = await repository.save_layout(
                project_id, workspace_id, 0, {"x": 0}, [{"id": str(task.id)}], []
            )
            with pytest.raises(AppError) as layout_conflict:
                await repository.save_layout(
                    project_id, workspace_id, 0, {"x": 100}, [{"id": str(task.id)}], []
                )
            assert layout_conflict.value.code == "WORKBENCH_LAYOUT_CONFLICT"
            persisted_layout = await repository.get_layout(project_id, workspace_id)
            assert persisted_layout is not None
            assert persisted_layout.layout_version == first_layout.layout_version == 1
            assert persisted_layout.viewport == {"x": 0}
        finally:
            await engine.dispose()

    asyncio.run(run())
