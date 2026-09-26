from dataclasses import dataclass
from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image

from backend.app.application.hero_prompting import resolve_constraint_cards
from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.ports import SystemClock
from backend.app.application.suite_planning_ports import (
    InMemoryPlanningReferenceResolver,
    PlanningReferenceRequest,
    PlanningReferenceSnapshot,
)
from backend.app.application.suite_planning_service import (
    SuitePlanCompilationInput,
    SuitePlanModuleInput,
    SuitePlanningService,
)
from backend.app.batch_generation_repository import InMemoryBatchGenerationRepository
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository
from backend.app.application.generation_config_service import GenerationConfigService
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage, project_asset_object_key
from backend.app.prompt_repository import MemoryPromptRepository
from backend.app.storage import StoredObject
from backend.app.suite_planning_repository import InMemorySuitePlanningRepository


@dataclass
class _CompilerRequest:
    module_id: str
    image_inputs: list[bytes]
    user_prompt: str


class RecordingSuitePlanner:
    def __init__(self) -> None:
        self.requests: list[_CompilerRequest] = []

    async def compile(self, request):
        self.requests.append(
            _CompilerRequest(request.module_id, list(request.image_inputs), request.user_prompt)
        )
        from backend.tests.test_module_planning_v2 import _result_payload
        result = _result_payload()
        result["copySummary"] = f"{request.module_id} content"
        return result



@pytest.mark.asyncio
async def test_suite_planning_compiles_all_source_images_and_freezes_snapshots() -> None:
    fixture = await _fixture()
    request = SuitePlanCompilationInput(
        source_asset_ids=fixture.source_asset_ids,
        market_id="taobao",
        model_id="gpt-image-2-5",
        style_id="minimal",
        aspect_ratio="3:4",
        resolution="标准 1K",
        output_language="中文",
        modules=[
            SuitePlanModuleInput("suite-hero", 2, [{"key": "标题", "value": "核心卖点"}]),
            SuitePlanModuleInput("suite-scene", 3, [{"key": "场景", "value": "书房"}]),
        ],
        user_notes="突出真实材质，不新增不存在的配件。",
        references=[PlanningReferenceRequest("ref-1", "v1")],
    )

    plan = await fixture.service.compile_plan(fixture.project_id, request, "suite-plan-1")
    detail = await fixture.plans.get_plan_detail(plan.id, fixture.workspace_id, fixture.project_id)

    assert plan.status == "awaiting_confirmation"
    assert detail is not None
    assert [(item.module_key, item.position, item.requested_image_count) for item in detail.modules] == [
        ("suite-hero", 1, 2),
        ("suite-scene", 2, 3),
    ]
    assert all(item.current_task_prompt.strip() for item in detail.modules)
    assert len(fixture.compiler.requests) == 2
    assert all(len(item.image_inputs) == 2 for item in fixture.compiler.requests)
    assert fixture.compiler.requests[0].user_prompt.find("真实材质") >= 0
    assert detail.plan.snapshot["sourceAssets"][0]["sha256"] == "a" * 64
    assert detail.plan.snapshot["references"][0]["referenceId"] == "ref-1"
    assert detail.modules[0].prompt_snapshot["modulePlanning"]["rendererVersion"]
    assert detail.modules[0].compiler_output["unconfirmedItems"]
    assert detail.modules[0].prompt_snapshot["constraints"]["market"]["content"]


@pytest.mark.asyncio
async def test_suite_planning_rejects_invalid_sources_or_modules_before_compiler() -> None:
    fixture = await _fixture()
    invalid = SuitePlanCompilationInput(
        source_asset_ids=[UUID(int=999)],
        market_id="taobao",
        model_id="gpt-image-2-5",
        style_id="minimal",
        aspect_ratio="3:4",
        resolution="标准 1K",
        output_language="中文",
        modules=[SuitePlanModuleInput("suite-hero", 5)],
    )

    with pytest.raises(AppError) as raised:
        await fixture.service.compile_plan(fixture.project_id, invalid, "suite-plan-invalid")

    assert raised.value.code == "SUITE_PLAN_INVALID_INPUT"
    assert fixture.compiler.requests == []
    assert await fixture.plans.get_by_compile_idempotency(fixture.workspace_id, "suite-plan-invalid") is None


async def _fixture():
    fixture = type("Fixture", (), {})()
    fixture.workspace_id = UUID(int=11)
    identity = LocalSingleUserIdentityProvider(IdentityContext(UUID(int=10), fixture.workspace_id, "owner"))
    fixture.projects = InMemoryProjectRepository()
    fixture.storage = MemoryProjectAssetStorage()
    fixture.prompts = MemoryPromptRepository()
    fixture.plans = InMemorySuitePlanningRepository()
    fixture.batches = InMemoryBatchGenerationRepository()
    fixture.compiler = RecordingSuitePlanner()
    fixture.references = InMemoryPlanningReferenceResolver([
        PlanningReferenceSnapshot("ref-1", "v1", fixture.workspace_id, "规格", "manual", "c" * 64, {"材质": "铝合金"})
    ])
    fixture.config = GenerationConfigService(
        InMemoryGenerationConfigRepository(), identity, MemoryIdempotencyStore(), SystemClock(), prompt_repository=fixture.prompts
    )
    project = await fixture.projects.create_project("详情页规划", fixture.workspace_id)
    fixture.project_id = project.id
    fixture.source_asset_ids = []
    for index, sha in enumerate(("a" * 64, "b" * 64), start=1):
        body = _png_bytes((index, index, index))
        object_id = UUID(int=30 + index)
        key = project_asset_object_key(fixture.workspace_id, project.id, object_id, "image/png")
        await fixture.storage.put(StoredObject(key, body, "image/png"))
        source_object = await fixture.projects.create_object(
            fixture.workspace_id, key, f"product-{index}.png", "image/png", len(body), 12, 8, sha, object_id=object_id
        )
        asset = await fixture.projects.create_asset(project.id, source_object.id, "source")
        fixture.source_asset_ids.append(asset.id)
    fixture.service = SuitePlanningService(
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        generation_config_service=fixture.config,
        prompt_repository=fixture.prompts,
        plan_repository=fixture.plans,
        reference_resolver=fixture.references,
        planner_compiler=fixture.compiler,
        identity_provider=identity,
        provider_model="gpt-image-2",
    )
    return fixture


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), color).save(output, format="PNG")
    return output.getvalue()
