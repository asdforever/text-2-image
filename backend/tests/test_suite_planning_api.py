from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage
from backend.app.suite_planning_repository import InMemorySuitePlanningRepository


class PlanningService:
    def __init__(self, detail) -> None:
        self.detail = detail
        self.calls = []

    async def compile_plan(self, project_id, payload, key):
        self.calls.append(("compile", project_id, payload, key))
        return self.detail.plan

    async def get_plan(self, project_id, plan_id):
        self.calls.append(("get", project_id, plan_id))
        return self.detail

    async def get_latest_plan(self, project_id):
        self.calls.append(("latest", project_id))
        return self.detail

    async def update_module(self, project_id, plan_id, payload):
        self.calls.append(("update", project_id, plan_id, payload))
        return self.detail

    async def reorder_modules(self, project_id, plan_id, module_ids, *, expected_plan_revision):
        self.calls.append(("order", project_id, plan_id, module_ids, expected_plan_revision))
        return self.detail


class ConfirmationService:
    async def confirm_plan(self, project_id, plan_id, **kwargs):
        self.call = (project_id, plan_id, kwargs)
        return SimpleNamespace(id=UUID(int=99))


@pytest.mark.asyncio
async def test_suite_planning_api_compiles_reads_edits_reorders_and_confirms() -> None:
    detail = _detail()
    service = PlanningService(detail)
    confirmation = ConfirmationService()
    app = create_app(
        settings=Settings(_env_file=None),
        repository=InMemoryRepository(),
        storage=MemoryObjectStorage(),
        suite_planning_service=service,
        suite_planning_confirmation_service=confirmation,
    )
    project_id, plan_id, module_id = UUID(int=22), UUID(int=55), UUID(int=66)
    compile_payload = {
        "sourceAssetIds": [str(UUID(int=33)), str(UUID(int=34))],
        "marketId": "taobao", "modelId": "gpt-image-2-5", "styleId": "minimal",
        "aspectRatio": "3:4", "resolution": "标准 1K", "outputLanguage": "中文",
        "modules": [{"moduleId": "suite-hero", "resultCount": 2, "moduleParameters": [], "taskDesign": {"productPresence": "context"}}],
        "references": [{"referenceId": "ref-1", "version": "v1"}],
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        compiled = await client.post(
            f"/api/projects/{project_id}/suite-plans/compile",
            headers={"Idempotency-Key": "compile-suite"}, json=compile_payload,
        )
        read = await client.get(f"/api/projects/{project_id}/suite-plans/{plan_id}")
        latest = await client.get(f"/api/projects/{project_id}/suite-plans/latest")
        edited = await client.patch(
            f"/api/projects/{project_id}/suite-plans/{plan_id}/modules/{module_id}",
            json={
                "expectedPlanRevision": 2, "expectedModuleRevision": 1,
                "visualDirection": "书房", "resultCount": 3,
            },
        )
        ordered = await client.patch(
            f"/api/projects/{project_id}/suite-plans/{plan_id}/order",
            json={"expectedPlanRevision": 2, "moduleIds": [str(module_id)]},
        )
        confirmed = await client.post(
            f"/api/projects/{project_id}/suite-plans/{plan_id}/confirm",
            headers={"Idempotency-Key": "confirm-suite"},
            json={"expectedPlanRevision": 2, "moduleTaskPrompts": {"suite-hero": "确认提示词"}},
        )

    assert compiled.status_code == 201
    assert read.status_code == latest.status_code == 200
    assert edited.status_code == ordered.status_code == confirmed.status_code == 200
    assert read.json()["data"]["modules"][0]["resultCount"] == 2
    assert read.json()["data"]["constraints"]["market"]["content"] == "平台约束"
    assert confirmed.json()["data"]["batchId"] == str(UUID(int=99))
    assert service.calls[0][3] == "compile-suite"
    assert service.calls[0][2].modules[0].task_design == {"productPresence": "context"}
    update_call = next(call for call in service.calls if call[0] == "update")
    assert update_call[3].requested_image_count == 3
    assert confirmation.call[2]["idempotency_key"] == "confirm-suite"


def _detail():
    now = datetime.now(timezone.utc)
    plan = SimpleNamespace(
        id=UUID(int=55), project_id=UUID(int=22), status="awaiting_confirmation",
        revision=2, snapshot={
            "sourceAssets": [{"assetId": str(UUID(int=33))}],
            "constraints": {"market": {"content": "平台约束"}},
            "references": [],
        },
        generation_batch_id=None, error_code=None, error_message=None,
        created_at=now, updated_at=now, confirmed_at=None,
    )
    module = SimpleNamespace(
        id=UUID(int=66), module_key="suite-hero", position=1,
        requested_image_count=2, revision=1, title="首屏", copy_summary="摘要",
        visual_direction="居中", module_parameters=[], prompt_snapshot={},
        compiled_task_prompt="编译提示词", compiler_output={"visibleFacts": ["黑色"], "unconfirmedItems": []},
        current_task_prompt="当前提示词",
    )
    return SimpleNamespace(plan=plan, modules=[module])


@pytest.mark.asyncio
async def test_suite_planning_repository_is_injectable_and_part_of_readiness() -> None:
    class UnreadyPlanningRepository(InMemorySuitePlanningRepository):
        async def ready(self) -> bool:
            return False

    repository = UnreadyPlanningRepository()
    app = create_app(
        settings=Settings(_env_file=None), repository=InMemoryRepository(),
        storage=MemoryObjectStorage(), suite_planning_repository=repository,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/ready")

    assert app.state.suite_planning_repository is repository
    assert response.status_code == 503
    assert "suitePlanning" in response.json()["error"]["message"]
