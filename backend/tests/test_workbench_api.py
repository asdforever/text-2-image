from uuid import uuid4

import httpx
import pytest

from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.workbench_repository import InMemoryWorkbenchRepository
from backend.app.application.workbench_service import WorkbenchService
from backend.app.core.identity import IdentityContext


@pytest.mark.asyncio
async def test_workbench_api_reads_edits_versions_layout_and_references() -> None:
    workspace_id = uuid4()
    app = create_app(
        settings=Settings(_env_file=None),
        identity_provider=LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner")),
        workbench_repository=InMemoryWorkbenchRepository(),
    )
    project_id, plan_id, item_id = uuid4(), uuid4(), uuid4()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/suites/{project_id}/tasks",
            headers={"Idempotency-Key": "task-api-1"},
            json={"planSnapshotId": str(plan_id), "tasks": [{"planItemId": str(item_id), "ordinal": 1, "title": "首屏", "purpose": "卖点", "promptDraft": "提示词", "generationParams": {}}]},
        )
        assert created.status_code == 201
        task = created.json()["data"]["tasks"][0]
        task_id = task["id"]
        edited = await client.patch(f"/api/suite-tasks/{task_id}", json={"expectedRevision": 1, "promptDraft": "新提示词"})
        assert edited.status_code == 200
        assert edited.json()["data"]["promptDraft"] == "新提示词"
        layout = await client.patch(f"/api/suites/{project_id}/workbench/layout", json={"layoutVersion": 0, "viewport": {"x": 1, "y": 2, "zoom": 1}, "nodes": [], "groups": []})
        assert layout.status_code == 200
        fetched = await client.get(f"/api/suites/{project_id}/workbench")
        assert fetched.status_code == 200
        assert fetched.json()["data"]["tasks"][0]["id"] == task_id


@pytest.mark.asyncio
async def test_workbench_generation_routes_return_existing_batch_without_provider() -> None:
    workspace_id, project_id, plan_id, batch_id = uuid4(), uuid4(), uuid4(), uuid4()

    class PlanService:
        async def get_plan(self, project_id, plan_id):
            return type("Detail", (), {"plan": type("Plan", (), {"id": plan_id, "status": "confirmed", "generation_batch_id": batch_id})()})()

    class BatchRepository:
        async def get_batch(self, requested_id, requested_workspace):
            if requested_id != batch_id or requested_workspace != workspace_id:
                return None
            return type("Batch", (), {"id": batch_id, "status": "queued"})()

    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    app = create_app(
        settings=Settings(_env_file=None),
        identity_provider=identity,
        workbench_repository=InMemoryWorkbenchRepository(),
    )
    app.state.workbench_service = WorkbenchService(
        app.state.workbench_repository,
        identity,
        suite_planning_service=PlanService(),
        batch_repository=BatchRepository(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            f"/api/suites/{project_id}/tasks",
            headers={"Idempotency-Key": "route-generation"},
            json={"planSnapshotId": str(plan_id), "tasks": [{"planItemId": str(uuid4()), "ordinal": 1, "title": "主图", "promptDraft": "提示词", "generationParams": {}}]},
        )
        task = created.json()["data"]["tasks"][0]

        single = await client.post(
            f"/api/suite-tasks/{task['id']}/generation",
            headers={"Idempotency-Key": "generation-same"},
            json={"expectedRevision": task["promptRevision"]},
        )
        assert single.status_code == 200
        assert single.json()["data"] == {"batchId": str(batch_id), "status": "running"}
        replay = await client.post(
            f"/api/suite-tasks/{task['id']}/generation",
            headers={"Idempotency-Key": "generation-same"},
            json={"expectedRevision": task["promptRevision"]},
        )
        assert replay.status_code == 200
        assert replay.json()["data"] == single.json()["data"]

        batch = await client.post(
            f"/api/suites/{project_id}/generation",
            json={"taskIds": [task["id"]]},
        )
        assert batch.status_code == 200
        assert batch.json()["data"] == {"batchId": str(batch_id), "status": "running"}


@pytest.mark.asyncio
async def test_workbench_task_patch_requires_revision_with_validation_error() -> None:
    app = create_app(settings=Settings(_env_file=None), workbench_repository=InMemoryWorkbenchRepository())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(f"/api/suite-tasks/{uuid4()}", json={"promptDraft": "缺少修订"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
