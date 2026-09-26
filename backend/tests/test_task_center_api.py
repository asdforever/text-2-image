from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage
from backend.tests.test_batch_generation_api import _detail as batch_detail
from backend.tests.test_suite_planning_api import _detail as plan_detail


@pytest.mark.asyncio
async def test_task_center_returns_project_grouped_hero_and_suite_summaries_without_writes():
    project_one = SimpleNamespace(id=UUID(int=1), name="项目一", status="active", updated_at=datetime.now(timezone.utc))
    project_two = SimpleNamespace(id=UUID(int=2), name="项目二", status="active", updated_at=datetime.now(timezone.utc))
    batch = batch_detail("running")
    batch.batch.project_id = project_one.id
    batch.batch.kind = "hero"
    batch.progress.total = 4
    batch.progress.succeeded = 2
    plan = plan_detail()
    plan.plan.project_id = project_two.id
    plan.plan.status = "awaiting_confirmation"

    class Projects:
        async def list_projects(self, include_archived=False):
            return [project_one, project_two]

    class Heroes:
        async def get_latest(self, project_id, workspace_id, **kwargs):
            return SimpleNamespace(
                id=UUID(int=11), project_id=project_one.id, status="awaiting_confirmation",
                created_at=batch.batch.created_at, updated_at=batch.batch.updated_at,
                error_code=None, error_message=None,
            ) if project_id == project_one.id else None

    class Batches:
        async def get_latest(self, project_id, workspace_id, **kwargs):
            return batch.batch if project_id == project_one.id else None

        async def get_batch_detail(self, batch_id, workspace_id):
            return batch

    class Plans:
        async def get_latest(self, project_id, workspace_id):
            return plan if project_id == project_two.id else None

    app = create_app(settings=Settings(_env_file=None), repository=InMemoryRepository(), storage=MemoryObjectStorage())
    app.state.project_service = Projects()
    app.state.hero_generation_repository = Heroes()
    app.state.batch_generation_repository = Batches()
    app.state.suite_planning_repository = Plans()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/task-center")

    assert response.status_code == 200
    groups = response.json()["data"]["projects"]
    assert {group["projectId"] for group in groups} == {str(project_one.id), str(project_two.id)}
    hero_group = next(group for group in groups if group["projectId"] == str(project_one.id))
    suite_group = next(group for group in groups if group["projectId"] == str(project_two.id))
    assert hero_group["tasks"][0]["type"] == "hero"
    assert hero_group["tasks"][0]["progress"] == {"succeeded": 2, "total": 4, "failed": 0, "cancelled": 0}
    assert suite_group["tasks"][0]["type"] == "suite"


@pytest.mark.asyncio
async def test_task_center_prefers_newest_task_for_each_type_and_keeps_error_details():
    project = SimpleNamespace(id=UUID(int=3), name="项目三", status="active")
    older = batch_detail("running")
    older.batch.project_id = project.id
    older.batch.kind = "hero"
    older.batch.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = SimpleNamespace(
        id=UUID(int=31), project_id=project.id, status="failed",
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        error_code=None, error_message="模型额度不足",
    )

    class Projects:
        async def list_projects(self, include_archived=False):
            return [project]

    class Heroes:
        async def get_latest(self, project_id, workspace_id, **kwargs):
            return newer

    class Batches:
        async def get_latest(self, project_id, workspace_id, **kwargs):
            return older.batch

        async def get_batch_detail(self, batch_id, workspace_id):
            return older

    class Plans:
        async def get_latest(self, project_id, workspace_id):
            return None

    app = create_app(settings=Settings(_env_file=None), repository=InMemoryRepository(), storage=MemoryObjectStorage())
    app.state.project_service = Projects()
    app.state.hero_generation_repository = Heroes()
    app.state.batch_generation_repository = Batches()
    app.state.suite_planning_repository = Plans()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/task-center")

    assert response.status_code == 200
    tasks = response.json()["data"]["projects"][0]["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["source"] == "hero_generation"
    assert tasks[0]["error"] == {"code": "TASK_FAILED", "message": "模型额度不足"}
