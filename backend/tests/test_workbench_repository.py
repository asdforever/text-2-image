from uuid import uuid4

import pytest

from backend.app.core.errors import AppError
from backend.app.workbench_repository import (
    InMemoryWorkbenchRepository,
    WorkbenchTaskInput,
    WorkbenchVersionInput,
)


@pytest.mark.asyncio
async def test_workbench_repository_creates_tasks_idempotently_and_edits_with_revision() -> None:
    repo = InMemoryWorkbenchRepository()
    workspace_id, project_id, plan_id = uuid4(), uuid4(), uuid4()
    first, duplicate = await repo.create_tasks(
        workspace_id,
        project_id,
        plan_id,
        "create-1",
        [WorkbenchTaskInput(uuid4(), 1, "详情", "卖点", "提示词", {"ratio": "1:1"})],
    )

    replay, is_replay = await repo.create_tasks(
        workspace_id,
        project_id,
        plan_id,
        "create-1",
        [WorkbenchTaskInput(first[0].plan_item_id, 1, "详情", "卖点", "提示词", {"ratio": "1:1"})],
    )
    assert len(first) == len(replay) == 1
    assert is_replay is True
    assert replay[0].id == first[0].id

    updated = await repo.update_task(first[0].id, workspace_id, 1, {"prompt_draft": "新提示词"})
    assert updated.prompt_draft == "新提示词"
    assert updated.prompt_revision == 2
    with pytest.raises(AppError, match="WORKBENCH_TASK_REVISION_CONFLICT"):
        await repo.update_task(first[0].id, workspace_id, 1, {"prompt_draft": "过期"})


@pytest.mark.asyncio
async def test_workbench_repository_selects_current_and_final_versions_without_mutating_history() -> None:
    repo = InMemoryWorkbenchRepository()
    workspace_id, project_id = uuid4(), uuid4()
    tasks, _ = await repo.create_tasks(
        workspace_id,
        project_id,
        uuid4(),
        "create-2",
        [WorkbenchTaskInput(uuid4(), 1, "详情", "", "", {})],
    )
    task = tasks[0]
    one = await repo.add_version(task.id, workspace_id, WorkbenchVersionInput("one", 1))
    two = await repo.add_version(task.id, workspace_id, WorkbenchVersionInput("two", 2))
    await repo.select_version(task.id, workspace_id, one.id, "current")
    await repo.select_version(task.id, workspace_id, two.id, "final")
    versions = await repo.list_versions(task.id, workspace_id)
    assert [item.object_key for item in versions] == ["one", "two"]
    assert next(item for item in versions if item.id == one.id).is_current is True
    assert next(item for item in versions if item.id == two.id).is_final is True


@pytest.mark.asyncio
async def test_workbench_repository_rejects_stale_layout_and_deduplicates_references() -> None:
    repo = InMemoryWorkbenchRepository()
    workspace_id, project_id, task_id = uuid4(), uuid4(), uuid4()
    saved = await repo.save_layout(project_id, workspace_id, 0, {"x": 1}, [{"nodeId": str(task_id)}], [])
    assert saved.layout_version == 1
    with pytest.raises(AppError, match="布局"):
        await repo.save_layout(project_id, workspace_id, 0, {"x": 2}, [], [])
    reference, duplicate = await repo.create_reference(
        workspace_id, project_id, "task", task_id, "input_image", uuid4(), "v1", {"sha256": "a"}
    )
    replay, duplicate_again = await repo.create_reference(
        workspace_id, project_id, "task", task_id, "input_image", reference.resource_id, "v1", {"sha256": "a"}
    )
    assert duplicate is False
    assert duplicate_again is True
    assert replay.id == reference.id
