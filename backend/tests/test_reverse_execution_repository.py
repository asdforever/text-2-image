from uuid import UUID, uuid4

import pytest

from app.core.errors import AppError
from app.reverse_execution_repository import InMemoryReverseExecutionRepository


@pytest.mark.asyncio
async def test_multiple_plans_survive_and_are_scoped_by_project_and_workspace():
    repository = InMemoryReverseExecutionRepository()
    workspace, project, version = uuid4(), uuid4(), uuid4()
    first = await repository.create(workspace, project, version, {"name": "方案一", "tasks": []})
    second = await repository.create(workspace, project, version, {"name": "方案二", "tasks": []})
    assert (await repository.get(workspace, project, first.id)).document["name"] == "方案一"
    assert [p.id for p in await repository.list(workspace, project)] == [second.id, first.id]
    assert await repository.get(uuid4(), project, first.id) is None
    assert await repository.get(workspace, uuid4(), first.id) is None
    saved = await repository.save(workspace, project, 1, {"name": "改名", "tasks": []}, plan_id=first.id)
    assert saved.id == first.id
    assert (await repository.get(workspace, project, second.id)).document["name"] == "方案二"


@pytest.mark.asyncio
async def test_execution_plan_create_and_save_are_revisioned():
    repository = InMemoryReverseExecutionRepository()
    workspace_id = uuid4()
    project_id = uuid4()
    version_id = uuid4()
    plan = {"versionId": str(version_id), "tasks": [{"id": "task-1"}], "revision": 1}

    created = await repository.create(workspace_id, project_id, version_id, plan)
    assert created.document["tasks"] == [{"id": "task-1"}]

    saved = await repository.save(
        workspace_id,
        project_id,
        expected_revision=1,
        document={**plan, "tasks": [{"id": "task-1", "promptDraft": "已编辑"}]},
    )

    assert saved.revision == 2
    assert saved.document["tasks"][0]["promptDraft"] == "已编辑"
    with pytest.raises(AppError) as error:
        await repository.save(workspace_id, project_id, 1, plan)
    assert error.value.code == "REVERSE_EXECUTION_REVISION_CONFLICT"
