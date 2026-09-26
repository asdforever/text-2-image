from uuid import UUID
from types import SimpleNamespace

import httpx
import pytest

from backend.app.main import create_app
from backend.app.core.config import Settings
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage
from backend.tests.test_batch_generation_api import _detail as batch_detail
from backend.tests.test_suite_planning_api import _detail as plan_detail


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["generation-batches", "suite-plans"])
async def test_recovery_by_request_key_is_read_only_and_project_scoped(kind):
    detail = batch_detail("compiling_prompt") if kind == "generation-batches" else plan_detail()
    record = detail.batch if kind == "generation-batches" else detail.plan
    record.error_code = "MODEL_NO_CREDIT"
    record.error_message = "模型额度不足"
    lookups = []

    class Repository:
        async def get_by_compile_idempotency(self, workspace_id, key):
            lookups.append((workspace_id, key))
            return record if key == "saved-request" else None

        async def get_batch_detail(self, task_id, workspace_id):
            return detail

        async def get_plan_detail(self, task_id, workspace_id, project_id):
            return detail

    app = create_app(settings=Settings(_env_file=None), repository=InMemoryRepository(), storage=MemoryObjectStorage())
    if kind == "generation-batches":
        app.state.batch_generation_repository = Repository()
    else:
        app.state.suite_planning_repository = Repository()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/projects/{record.project_id}/{kind}/by-request"
        found = await client.get(url, params={"key": "saved-request"})
        missing = await client.get(url, params={"key": "unknown"})
        other = await client.get(f"/api/projects/{UUID(int=999)}/{kind}/by-request", params={"key": "saved-request"})
    assert found.status_code == 200
    assert found.json()["data"]["id"] == str(record.id)
    assert found.json()["data"]["error"]["message"] == "模型额度不足"
    assert missing.status_code == 200 and missing.json()["data"] is None
    assert other.status_code == 404
    assert all(item[0] == app.state.identity_provider.get_context().workspace_id for item in lookups)
