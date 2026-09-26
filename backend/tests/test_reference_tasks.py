from copy import deepcopy
from dataclasses import replace
import json
from uuid import uuid4

import pytest

from backend.app.core.errors import AppError
from backend.tests.test_module_planning import fixture
from backend.tests.test_batch_generation_compile_service import _fixture as hero_fixture, _input
from backend.app.application.batch_generation_service import BatchHeroModuleInput
from backend.app.application.suite_planning_service import SuitePlanModuleInput, SuitePlanCompilationInput


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hero", "suite"])
async def test_master_repeated_catalog_module_has_independent_tasks(mode):
    f = await fixture(mode)
    original = f.master.result["modules"][0]
    f.master.result["modules"] = [{**deepcopy(original), "taskId": f"task-{i}"} for i in range(2)]
    result = await f.master_service.plan(f.project_id, f.input, "tasks")
    assert [m["taskId"] for m in result["modules"]] == ["task-0", "task-1"]
    f.master.result["modules"][1]["taskId"] = "task-0"
    with pytest.raises(AppError):
        await f.master_service.plan(f.project_id, f.input, "duplicate")


@pytest.mark.asyncio
async def test_reference_roles_order_and_pre_call_snapshot():
    f = await fixture()
    product, reference = f.source_asset_ids
    payload = f.input.model_copy(update={"sourceAssetIds": [product], "referenceAssetIds": [reference]})
    original = f.master.plan_modules
    async def check(request):
        saved = await f.master_service.latest(f.project_id, "suite")
        roles = json.loads(request.user_prompt)["imageRoles"]
        assert roles == [{"imageIndex": 1, "assetId": str(product), "role": "product", "order": 1},
                         {"imageIndex": 2, "assetId": str(reference), "role": "reference", "order": 1}]
        assert saved["snapshot"]["imageRoles"] == roles
        assert saved["snapshot"]["referenceAssets"][0]["assetId"] == str(reference)
        assert len(saved["snapshot"]["sourceAssets"]) == 1
        assert len(request.image_inputs) == 2
        return await original(request)
    f.master.plan_modules = check
    await f.master_service.plan(f.project_id, payload, "references")
    with pytest.raises(AppError):
        await f.master_service.plan(f.project_id, payload.model_copy(update={"referenceAssetIds": [product]}), "overlap")
    assert len(f.master.calls) == 1


@pytest.mark.asyncio
async def test_hero_same_module_compiles_independent_prompts_and_keys():
    f = await hero_fixture()
    request = replace(_input(f.source_asset_id), modules=[BatchHeroModuleInput("hero-kv", i + 1,
        [{"key": "内容", "value": f"内容{i}"}], task_id=f"task-{i}") for i in range(2)])
    batch = await f.service.compile_prompt_batch(f.project_id, request, "tasks")
    detail = await f.repository.get_batch_detail(batch.id, f.workspace_id)
    assert [m.module_key for m in detail.module_tasks] == ["task-0", "task-1"]
    assert len({m.compiled_task_prompt for m in detail.module_tasks}) == 2
    assert [m.snapshot["selection"]["module"]["id"] for m in detail.module_tasks] == ["hero-kv"] * 2
    from backend.app.application.batch_generation_confirmation_service import BatchGenerationConfirmationService
    from backend.app.routes.batch_generations import _detail_view
    confirmation = BatchGenerationConfirmationService(f.repository, f.service.identity_provider)
    await confirmation.confirm_batch(f.project_id, batch.id, {m.module_key: m.compiled_task_prompt for m in detail.module_tasks}, "confirm")
    confirmed = await f.repository.get_batch_detail(batch.id, f.workspace_id)
    assert [s.module_key for s in confirmed.slots] == ["task-0", "task-1", "task-1"]
    assert [m["moduleId"] for m in _detail_view(confirmed, f.project_id)["modules"]] == ["hero-kv"] * 2
    assert [s["taskId"] for s in _detail_view(confirmed, f.project_id)["slots"]] == ["task-0", "task-1", "task-1"]
    with pytest.raises(AppError):
        await f.service.compile_prompt_batch(f.project_id, replace(request, modules=[request.modules[0]] * 2), "bad")


@pytest.mark.asyncio
async def test_suite_same_module_compiles_independent_parameters_and_keys():
    f = await fixture()
    request = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids, market_id="taobao",
        model_id="gpt-image-2-5", style_id="minimal", aspect_ratio="3:4", resolution="标准 1K",
        output_language="中文", modules=[SuitePlanModuleInput("suite-hero", i + 1,
        [{"key": "内容", "value": f"内容{i}"}], task_id=f"task-{i}") for i in range(2)])
    plan = await f.service.compile_plan(f.project_id, request, "tasks")
    detail = await f.plans.get_plan_detail(plan.id, f.workspace_id, f.project_id)
    assert [m.module_key for m in detail.modules] == ["task-0", "task-1"]
    assert "内容0" in f.compiler.requests[0].user_prompt
    assert "内容1" in f.compiler.requests[1].user_prompt
    from backend.app.application.suite_planning_confirmation_service import SuitePlanningConfirmationService
    from backend.app.routes.batch_generations import _detail_view
    confirmation = SuitePlanningConfirmationService(plan_repository=f.plans, batch_repository=f.batches,
        identity_provider=f.service.identity_provider)
    batch = await confirmation.confirm_plan(f.project_id, plan.id, expected_plan_revision=plan.revision,
        module_task_prompts={m.module_key: m.compiled_task_prompt for m in detail.modules}, idempotency_key="confirm")
    confirmed = await f.batches.get_batch_detail(batch.id, f.workspace_id)
    assert [s.module_key for s in confirmed.slots] == ["task-0", "task-1", "task-1"]
    assert [m["moduleId"] for m in _detail_view(confirmed, f.project_id)["modules"]] == ["suite-hero"] * 2
    assert [m.confirmed_task_prompt for m in confirmed.module_tasks] == [m.compiled_task_prompt for m in detail.modules]
    with pytest.raises(AppError):
        await f.service.compile_plan(f.project_id, replace(request, modules=[request.modules[0]] * 2), "bad")


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing", "project", "workspace", "unavailable", "duplicate"])
async def test_invalid_references_never_reach_provider(invalid):
    f = await fixture()
    product, reference = f.source_asset_ids
    asset = await f.projects.get_asset(reference, f.workspace_id)
    if invalid == "missing":
        reference = uuid4()
    elif invalid in {"project", "workspace"}:
        other = await f.projects.create_project("Other", uuid4() if invalid == "workspace" else f.workspace_id)
        asset.project_id = other.id
    elif invalid == "unavailable":
        asset.state = "deleted"
    payload = f.input.model_copy(update={"sourceAssetIds": [product],
        "referenceAssetIds": [reference] * (2 if invalid == "duplicate" else 1)})
    with pytest.raises(AppError):
        await f.master_service.plan(f.project_id, payload, "bad-ref")
    assert f.master.calls == []


@pytest.mark.asyncio
async def test_reference_order_changes_fingerprint_and_image_order():
    f = await fixture()
    first, second = f.source_asset_ids
    first_asset = await f.projects.get_asset(first, f.workspace_id)
    product = await f.projects.create_asset(f.project_id, first_asset.object_id, "source")
    payload = f.input.model_copy(update={"sourceAssetIds": [product.id], "referenceAssetIds": [second, first]})
    result = await f.master_service.plan(f.project_id, payload, "ordered")
    assert [a["assetId"] for a in result["snapshot"]["referenceAssets"]] == [str(second), str(first)]
    assert f.master.calls[0].image_inputs[0] == f.master.calls[0].image_inputs[2]
    assert f.master.calls[0].image_inputs[1] != f.master.calls[0].image_inputs[2]
    with pytest.raises(AppError) as error:
        await f.master_service.plan(f.project_id, payload.model_copy(update={"referenceAssetIds": [first, second]}), "ordered")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
