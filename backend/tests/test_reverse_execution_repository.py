from uuid import UUID, uuid4

import pytest

from app.core.errors import AppError
from app.reverse_execution_repository import InMemoryReverseExecutionRepository


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
