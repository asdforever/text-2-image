import json
from dataclasses import asdict
from uuid import UUID

import httpx
import pytest

from backend.app.application.batch_generation_service import (
    BatchHeroModuleInput,
    BatchHeroPromptCompilationInput,
)
from backend.app.application.hero_generation_ports import ImageEditInput, PromptCompileRequest
from backend.app.application.idempotency import request_fingerprint
from backend.app.application.reverse_project_service import ReverseProjectService
from backend.app.application.suite_planning_service import (
    SuitePlanCompilationInput,
    SuitePlanModuleInput,
)
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.providers.openai_compatible import OpenAICompatiblePromptCompiler
from backend.app.reverse_project_repository import InMemoryReverseProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage
from backend.tests.test_batch_generation_compile_service import _fixture as batch_fixture
from backend.tests.test_batch_generation_compile_service import _input as batch_input
from backend.tests.test_module_planning import fixture as master_fixture
from backend.tests.test_reverse_projects import editable_document, png_bytes
from backend.tests.test_suite_planning_service import _fixture as suite_fixture


async def _published_reverse(
    workspace_id: UUID,
    *,
    repository: InMemoryReverseProjectRepository | None = None,
    storage: MemoryProjectAssetStorage | None = None,
):
    repository = repository or InMemoryReverseProjectRepository()
    storage = storage or MemoryProjectAssetStorage()
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=910), workspace_id, "owner")
    )
    service = ReverseProjectService(repository, identity, storage=storage)
    project = await service.create_project("竞品详情页", "厨房电器")
    project = await service.add_reference(
        project.id, "reference.png", "image/png", png_bytes("red")
    )
    reference_id = project.references[0].id
    project = await service.update_project(
        project.id, project.revision, editable_document(str(reference_id))
    )
    version = await service.publish(project.id, project.revision)
    return service, version, repository, storage


@pytest.mark.asyncio
async def test_master_uses_only_reverse_overview_and_validates_reference_module() -> None:
    fixture = await master_fixture("suite")
    reverse, version, repository, storage = await _published_reverse(fixture.workspace_id)
    fixture.master_service.reverse_projects = reverse
    fixture.master.result["modules"][0]["referenceModuleId"] = "benefit-proof"
    payload = fixture.input.model_copy(update={"reverseVersionId": version.id})

    result = await fixture.master_service.plan(fixture.project_id, payload, "reverse-master")

    prompt = json.loads(fixture.master.calls[0].user_prompt)
    reverse_context = prompt["reversePlanning"]
    assert reverse_context["versionId"] == str(version.id)
    assert reverse_context["modules"] == [
        {"id": "benefit-proof", "title": "核心卖点证据", "goal": "说明快速出餐的依据"}
    ]
    assert "layout" not in reverse_context["modules"][0]
    assert result["modules"][0]["referenceModuleId"] == "benefit-proof"
    assert result["snapshot"]["reversePlanning"] == reverse_context
    assert len(fixture.master.calls[0].image_inputs) == len(payload.sourceAssetIds)

    other_identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=911), UUID(int=999), "owner")
    )
    fixture.master_service.reverse_projects = ReverseProjectService(
        repository, other_identity, storage=storage
    )
    with pytest.raises(AppError) as hidden:
        await fixture.master_service.plan(
            fixture.project_id, payload, "reverse-master-other-workspace"
        )
    assert hidden.value.code == "REVERSE_VERSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_master_rejects_reference_module_outside_selected_version() -> None:
    fixture = await master_fixture("suite")
    reverse, version, _, _ = await _published_reverse(fixture.workspace_id)
    fixture.master_service.reverse_projects = reverse
    fixture.master.result["modules"][0]["referenceModuleId"] = "unknown-module"

    with pytest.raises(AppError) as raised:
        await fixture.master_service.plan(
            fixture.project_id,
            fixture.input.model_copy(update={"reverseVersionId": version.id}),
            "reverse-master-invalid-module",
        )

    assert raised.value.code == "MODULE_PLANNER_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_batch_compiler_receives_selected_reverse_module_and_image() -> None:
    fixture = await batch_fixture(planner_version="v2")
    reverse, version, _, _ = await _published_reverse(fixture.workspace_id)
    fixture.service.reverse_projects = reverse
    original = batch_input(fixture.source_asset_id)
    request = BatchHeroPromptCompilationInput(
        **{
            **original.__dict__,
            "reverse_version_id": version.id,
            "modules": [
                BatchHeroModuleInput(
                    "hero-kv",
                    1,
                    reverse_reference={
                        "versionId": version.id,
                        "moduleId": "benefit-proof",
                    },
                ),
                BatchHeroModuleInput("hero-scene", 1),
            ],
        }
    )

    batch = await fixture.service.compile_prompt_batch(
        fixture.project_id, request, "reverse-batch"
    )
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)

    assert batch.snapshot["reversePlanning"]["versionId"] == str(version.id)
    assert len(fixture.compiler.requests[0].ordered_image_inputs()) == 2
    assert len(fixture.compiler.requests[1].ordered_image_inputs()) == 1
    reference = detail.module_tasks[0].snapshot["reverseReference"]
    assert reference["context"]["modules"][0]["layout"] == "左侧产品，右侧三层信息"
    assert reference["imageMimeTypes"] == ["image/png"]
    compiler_context = json.loads(fixture.compiler.requests[0].user_prompt)
    assert compiler_context["additionalContext"]["reverseReference"]["role"] == "competitor_design_reference"
    assert "current product facts" in compiler_context["additionalContext"]["reverseReference"]["factPolicy"]


@pytest.mark.asyncio
async def test_batch_uses_master_reference_only_for_matching_reverse_version() -> None:
    fixture = await batch_fixture(planner_version="v2")
    reverse, version, _, _ = await _published_reverse(fixture.workspace_id)
    fixture.service.reverse_projects = reverse
    plan_id = UUID(int=740)

    class MasterPlanning:
        async def snapshot(self, _project_id, _plan_id, _mode):
            return {
                "id": str(plan_id),
                "status": "completed",
                "planningContractVersion": "commerce-design-v1",
                "sharedVisualDirection": "统一品牌层级",
                "input": {"reverseVersionId": str(version.id)},
                "modules": [
                    {
                        "moduleId": "hero-kv",
                        "taskId": "hero-kv",
                        "taskTitle": "建立商品识别",
                        "designGuideIds": ["visual-hierarchy"],
                        "productPresence": "full",
                        "referenceModuleId": "benefit-proof",
                    }
                ],
            }

    fixture.service.module_planning = MasterPlanning()
    original = batch_input(fixture.source_asset_id)
    request = BatchHeroPromptCompilationInput(
        **{
            **original.__dict__,
            "module_plan_id": plan_id,
            "reverse_version_id": version.id,
            "modules": [BatchHeroModuleInput("hero-kv", 1)],
        }
    )
    await fixture.service.compile_prompt_batch(
        fixture.project_id, request, "reverse-batch-master"
    )
    assert len(fixture.compiler.requests[0].ordered_image_inputs()) == 2

    mismatch = BatchHeroPromptCompilationInput(
        **{**request.__dict__, "reverse_version_id": UUID(int=741)}
    )
    with pytest.raises(AppError) as raised:
        await fixture.service.compile_prompt_batch(
            fixture.project_id, mismatch, "reverse-batch-mismatch"
        )
    assert raised.value.code == "REVERSE_PLANNING_VERSION_MISMATCH"
    assert raised.value.status_code == 409


@pytest.mark.asyncio
async def test_suite_compiler_appends_reverse_image_and_freezes_module_context() -> None:
    fixture = await suite_fixture()
    reverse, version, _, _ = await _published_reverse(fixture.workspace_id)
    fixture.service.reverse_projects = reverse
    request = SuitePlanCompilationInput(
        source_asset_ids=fixture.source_asset_ids,
        market_id="taobao",
        model_id="gpt-image-2-5",
        style_id="minimal",
        aspect_ratio="3:4",
        resolution="标准 1K",
        output_language="中文",
        reverse_version_id=version.id,
        modules=[
            SuitePlanModuleInput(
                "suite-hero",
                1,
                reverse_reference={
                    "versionId": version.id,
                    "moduleId": "benefit-proof",
                },
            ),
            SuitePlanModuleInput("suite-scene", 1),
        ],
    )

    plan = await fixture.service.compile_plan(
        fixture.project_id, request, "reverse-suite"
    )
    detail = await fixture.plans.get_plan_detail(
        plan.id, fixture.workspace_id, fixture.project_id
    )

    assert plan.snapshot["reversePlanning"]["versionId"] == str(version.id)
    assert len(fixture.compiler.requests[0].image_inputs) == 3
    assert len(fixture.compiler.requests[1].image_inputs) == 2
    assert detail.modules[0].prompt_snapshot["reverseReference"]["context"]["modules"][0]["id"] == "benefit-proof"
    compiler_context = json.loads(fixture.compiler.requests[0].user_prompt)
    assert compiler_context["additionalContext"]["reverseReference"]["role"] == "competitor_design_reference"


@pytest.mark.asyncio
async def test_absent_reverse_fields_preserve_batch_fingerprint_shape() -> None:
    fixture = await batch_fixture(planner_version="v2")
    request = batch_input(fixture.source_asset_id)

    batch = await fixture.service.compile_prompt_batch(
        fixture.project_id, request, "no-reverse-compatible"
    )

    historical = asdict(request)
    for module in historical["modules"]:
        module.pop("task_id", None)
        module.pop("reverse_reference", None)
    historical.pop("reverse_version_id", None)
    assert batch.compile_fingerprint == request_fingerprint(historical)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hero", "suite"])
async def test_every_module_inherits_overall_rules_even_with_a_different_local_version(mode):
    fixture = await batch_fixture(planner_version="v2") if mode == "hero" else await suite_fixture()
    reverse, overall_version, repository, storage = await _published_reverse(fixture.workspace_id)
    _, local_version, _, _ = await _published_reverse(
        fixture.workspace_id, repository=repository, storage=storage
    )
    fixture.service.reverse_projects = reverse
    reference = {"versionId": local_version.id, "moduleId": "benefit-proof"}
    if mode == "hero":
        original = batch_input(fixture.source_asset_id)
        request = BatchHeroPromptCompilationInput(**{
            **original.__dict__,
            "reverse_version_id": overall_version.id,
            "modules": [BatchHeroModuleInput("hero-kv", 1, reverse_reference=reference), BatchHeroModuleInput("hero-scene", 1)],
        })
        await fixture.service.compile_prompt_batch(fixture.project_id, request, "overall-priority")
    else:
        request = SuitePlanCompilationInput(
            source_asset_ids=fixture.source_asset_ids, market_id="taobao",
            model_id="gpt-image-2-5", style_id="minimal", aspect_ratio="3:4",
            resolution="标准 1K", output_language="中文", reverse_version_id=overall_version.id,
            modules=[SuitePlanModuleInput("suite-hero", 1, reverse_reference=reference), SuitePlanModuleInput("suite-scene", 1)],
        )
        await fixture.service.compile_plan(fixture.project_id, request, "overall-priority")
    for compiled in fixture.compiler.requests:
        context = json.loads(compiled.user_prompt)["additionalContext"]
        assert context["reversePlanning"]["versionId"] == str(overall_version.id)
        assert context["reversePlanning"]["overall"] == overall_version.document["overall"]
        assert "overall reverse plan" in compiled.system_prompt
    local_context = json.loads(fixture.compiler.requests[0].user_prompt)["additionalContext"]
    assert local_context["reverseReference"]["context"]["versionId"] == str(local_version.id)
    assert "reverseReference" not in json.loads(fixture.compiler.requests[1].user_prompt)["additionalContext"]


@pytest.mark.asyncio
async def test_openai_prompt_compiler_sends_all_ordered_images() -> None:
    captured = {}

    def handle(request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "imagePrompt": "商品主体清晰，浅色背景，真实材质。",
                                    "copySummary": "卖点",
                                    "visualDirection": "居中构图",
                                    "exactCopy": [],
                                    "visibleFacts": ["商品可见"],
                                    "unconfirmedItems": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatiblePromptCompiler(
        base_url="https://test.invalid",
        api_key="test-only",
        model="fake",
        timeout_ms=1000,
        transport=httpx.MockTransport(handle),
    )
    request = PromptCompileRequest(
        system_prompt="system",
        user_prompt="user",
        image_bytes=b"product",
        image_mime_type="image/png",
        image_inputs=(
            ImageEditInput(b"product", "image/png", "product.png"),
            ImageEditInput(b"reference", "image/jpeg", "reference.jpg"),
        ),
    )

    await provider.compile(request)

    content = captured["messages"][1]["content"]
    assert [item["type"] for item in content] == ["text", "image_url", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
