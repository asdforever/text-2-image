from uuid import uuid4

import pytest

from backend.app.application.workbench_service import WorkbenchService
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.workbench_repository import InMemoryWorkbenchRepository, WorkbenchTaskInput


class _PlanService:
    def __init__(self, plan_id, batch_id):
        self.plan_id = plan_id
        self.batch_id = batch_id

    async def get_plan(self, project_id, plan_id):
        return type("Detail", (), {"plan": type("Plan", (), {"id": plan_id, "status": "confirmed", "generation_batch_id": self.batch_id})(), "modules": []})()


class _BatchRepository:
    def __init__(self, batch_id, workspace_id, project_id):
        self.batch = type("Batch", (), {"id": batch_id, "workspace_id": workspace_id, "project_id": project_id, "status": "queued"})()

    async def get_batch(self, batch_id, workspace_id):
        return self.batch if self.batch.id == batch_id and self.batch.workspace_id == workspace_id else None


@pytest.mark.asyncio
async def test_workbench_service_scopes_tasks_and_returns_conflict_state() -> None:
    workspace_id, project_id = uuid4(), uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    repo = InMemoryWorkbenchRepository()
    service = WorkbenchService(repo, identity)
    tasks, _ = await service.create_tasks(
        project_id, uuid4(), "key", [WorkbenchTaskInput(uuid4(), 1, "首屏", "卖点", "提示词", {})]
    )
    with pytest.raises(AppError, match="WORKBENCH_TASK_REVISION_CONFLICT"):
        await service.update_task(tasks[0].id, 0, {"prompt_draft": "旧"})
    view = await service.get_task(tasks[0].id)
    assert view is not None
    assert view.project_id == project_id


@pytest.mark.asyncio
async def test_workbench_generation_reuses_confirmed_plan_batch_without_provider_call() -> None:
    workspace_id, project_id, plan_id, batch_id = uuid4(), uuid4(), uuid4(), uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    repo = InMemoryWorkbenchRepository()
    service = WorkbenchService(repo, identity, _PlanService(plan_id, batch_id), _BatchRepository(batch_id, workspace_id, project_id))
    tasks, _ = await service.create_tasks(project_id, plan_id, "create", [WorkbenchTaskInput(uuid4(), 1, "首屏", "", "提示词", {})])

    batch = await service.start_task_generation(tasks[0].id, tasks[0].prompt_revision)

    assert batch.id == batch_id
    assert batch.status == "queued"


@pytest.mark.asyncio
async def test_workbench_batch_generation_reuses_one_confirmed_batch_for_active_tasks() -> None:
    workspace_id, project_id, plan_id, batch_id = uuid4(), uuid4(), uuid4(), uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    repo = InMemoryWorkbenchRepository()
    service = WorkbenchService(repo, identity, _PlanService(plan_id, batch_id), _BatchRepository(batch_id, workspace_id, project_id))
    tasks, _ = await service.create_tasks(
        project_id,
        plan_id,
        "create-batch",
        [
            WorkbenchTaskInput(uuid4(), 1, "主图", "", "主图提示词", {}),
            WorkbenchTaskInput(uuid4(), 2, "详情", "", "详情提示词", {}),
        ],
    )

    batch = await service.start_batch_generation(project_id, [task.id for task in tasks])

    assert batch.id == batch_id
    assert batch.status == "queued"


@pytest.mark.asyncio
async def test_workbench_aggregate_maps_confirmed_plan_to_json_snapshot() -> None:
    workspace_id, project_id, plan_id = uuid4(), uuid4(), uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    repo = InMemoryWorkbenchRepository()

    class PlanService:
        async def get_latest_plan(self, requested_project_id):
            now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            plan = type("Plan", (), {
                "id": plan_id, "project_id": project_id, "status": "confirmed", "revision": 3,
                "snapshot": {"sourceAssets": ["asset-1"]}, "generation_batch_id": None,
                "confirmed_at": now, "created_at": now,
            })()
            module = type("Module", (), {
                "id": uuid4(), "position": 1, "title": "主图", "copy_summary": "卖点",
                "current_task_prompt": "最终提示词", "compiled_task_prompt": "编译提示词",
                "requested_image_count": 2, "module_parameters": [{"key": "颜色", "value": "黑色"}],
            })()
            return type("Detail", (), {"plan": plan, "modules": [module]})()

    service = WorkbenchService(repo, identity, suite_planning_service=PlanService())
    aggregate = await service.get_workbench(project_id)

    assert aggregate["planSnapshot"]["id"] == str(plan_id)
    assert aggregate["planSnapshot"]["revisionNumber"] == 3
    assert aggregate["planSnapshot"]["confirmationStatus"] == "confirmed"
    assert aggregate["planSnapshot"]["items"][0]["title"] == "主图"


@pytest.mark.asyncio
async def test_workbench_reference_rejects_target_from_another_project() -> None:
    workspace_id = uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    repo = InMemoryWorkbenchRepository()
    service = WorkbenchService(repo, identity)
    project_id, other_project_id = uuid4(), uuid4()
    target_id = uuid4()
    await repo.create_tasks(workspace_id, other_project_id, uuid4(), "other", [WorkbenchTaskInput(target_id, 1, "其他", "", "", {})])

    with pytest.raises(AppError, match="WORKBENCH_REFERENCE_SCOPE"):
        await service.create_reference(project_id, "task", target_id, "input_image", uuid4(), "v1", {})


@pytest.mark.asyncio
async def test_archived_task_is_hidden_but_retained_and_cannot_generate() -> None:
    workspace_id, project_id = uuid4(), uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    repo = InMemoryWorkbenchRepository()
    service = WorkbenchService(repo, identity)
    tasks, _ = await service.create_tasks(project_id, uuid4(), "archive", [WorkbenchTaskInput(uuid4(), 1, "详情", "", "", {})])

    archived = await service.archive_task(tasks[0].id)

    assert archived.archived_at is not None
    assert await service.list_tasks(project_id) == []
    assert (await service.list_tasks(project_id, include_archived=True))[0].id == tasks[0].id
    with pytest.raises(AppError, match="WORKBENCH_TASK_ARCHIVED"):
        await service.start_task_generation(tasks[0].id, tasks[0].prompt_revision)
