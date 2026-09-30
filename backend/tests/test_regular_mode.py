import pytest
from backend.tests.test_module_planning import fixture
from backend.app.application.module_planning_service import ModulePlanInput

@pytest.mark.asyncio
async def test_regular_planner_allocates_content_with_one_lightweight_model_call():
    f = await fixture()
    f.master.result = {"summary":"商品说明", "modules":[{"taskId":"a", "moduleId":"suite-hero", "taskTitle":"材质", "reason":"解释材质", "suggestedCopy":"纯棉", "moduleParameters":[{"key":"材质","value":"纯棉"}]}], "warnings":[]}
    request = f.input.model_copy(update={"creationMode":"regular", "brief":"材质：纯棉", "selectedModules":[{"taskId":"a","moduleId":"suite-hero"}]})
    result = await f.master_service.plan(f.project_id, request, "regular-content")
    assert len(f.master.calls) == 1
    assert result["modules"][0]["moduleParameters"] == [{"key":"材质","value":"纯棉"}]
    assert result["planningContractVersion"] == "regular-design-v1"
    assert "designKnowledge" not in result["snapshot"]
from dataclasses import replace
from backend.tests.test_batch_generation_compile_service import _fixture as hero_fixture, _input
from backend.tests.test_suite_planning_service import _fixture as suite_fixture
from backend.app.application.suite_planning_service import SuitePlanCompilationInput, SuitePlanModuleInput
from backend.app.application.batch_generation_confirmation_service import BatchGenerationConfirmationService
from backend.app.application.suite_planning_confirmation_service import SuitePlanningConfirmationService
from backend.app.batch_generation_repository import InMemoryBatchGenerationRepository

@pytest.mark.asyncio
async def test_regular_hero_compilation_confirm_and_replay_preserve_frozen_prompt():
    f = await hero_fixture()
    original = _input(f.source_asset_id)
    req = replace(original, creation_mode="regular", modules=[replace(original.modules[0], regular_task={"goal":"Show cotton", "copy":"Cotton"}, module_parameters=[{"key":"Material","value":"Cotton"}])])
    batch = await f.service.compile_prompt_batch(f.project_id, req, "regular")
    detail = await f.repository.get_batch_detail(batch.id, f.workspace_id)
    assert not f.compiler.requests
    task = detail.module_tasks[0]
    assert 'Cotton' in task.compiled_task_prompt
    assert task.snapshot["recipe"]["source_id"] == "evolink-product-local-v1"
    confirmation = BatchGenerationConfirmationService(f.repository, f.service.identity_provider)
    prompts = {task.module_key:task.compiled_task_prompt}
    await confirmation.confirm_batch(f.project_id,batch.id,prompts,"confirm")
    replay = await f.service.compile_prompt_batch(f.project_id,req,"regular")
    frozen = await f.repository.get_batch_detail(replay.id,f.workspace_id)
    assert frozen.module_tasks[0].final_prompt == task.compiled_task_prompt
    assert not f.compiler.requests

@pytest.mark.asyncio
async def test_regular_suite_compilation_confirm_freezes_prompt_without_v2():
    f = await suite_fixture()
    req = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids, market_id="taobao", model_id="gpt-image-2-5", style_id="minimal",aspect_ratio="3:4",resolution="标准 1K",output_language="中文",creation_mode="regular",modules=[SuitePlanModuleInput("suite-hero",1,[{"key":"Material","value":"Cotton"}],regular_task={"goal":"Show material","copy":"Cotton"})])
    plan = await f.service.compile_plan(f.project_id,req,"regular")
    detail = await f.plans.get_plan_detail(plan.id,f.workspace_id,f.project_id)
    assert not f.compiler.requests
    module = detail.modules[0]
    assert 'Cotton' in module.compiled_task_prompt
    batches = InMemoryBatchGenerationRepository()
    confirmation = SuitePlanningConfirmationService(plan_repository=f.plans,batch_repository=batches,identity_provider=f.service.identity_provider)
    batch = await confirmation.confirm_plan(f.project_id,plan.id,expected_plan_revision=detail.plan.revision,module_task_prompts={module.module_key:module.compiled_task_prompt},idempotency_key="confirm")
    frozen = await batches.get_batch_detail(batch.id,f.workspace_id)
    assert frozen.module_tasks[0].final_prompt == module.compiled_task_prompt
    assert frozen.module_tasks[0].snapshot["promptSnapshot"]["recipe"]["source_id"] == "evolink-product-local-v1"
@pytest.mark.asyncio
async def test_regular_planner_preserves_explicit_task_order_and_separate_fact_allocations():
    f = await fixture()
    modules = [{"taskId":"second","moduleId":"suite-detail","taskTitle":"Details","reason":"Explain material","suggestedCopy":"Cotton","moduleParameters":[{"key":"material","value":"cotton"}]}, {"taskId":"first","moduleId":"suite-hero","taskTitle":"Identity","reason":"Recognize product","suggestedCopy":"Shirt","moduleParameters":[{"key":"product","value":"shirt"}]}]
    f.master.result = {"summary":"Facts assigned", "modules":modules,"warnings":[]}
    req = f.input.model_copy(update={"creationMode":"regular", "selectedModules":[{"taskId":"first","moduleId":"suite-hero"},{"taskId":"second","moduleId":"suite-detail"}]})
    result = await f.master_service.plan(f.project_id,req,"order")
    assert [m["taskId"] for m in result["modules"]] == ["first","second"]
    assert result["modules"][1]["moduleParameters"] == [{"key":"material","value":"cotton"}]
    assert len(f.master.calls) == 1

@pytest.mark.asyncio
async def test_regular_slot_retry_reuses_frozen_recipe_and_prompt():
    f = await hero_fixture()
    req = replace(_input(f.source_asset_id),creation_mode="regular")
    batch = await f.service.compile_prompt_batch(f.project_id,req,"retry-compile")
    detail = await f.repository.get_batch_detail(batch.id,f.workspace_id)
    prompts = {t.module_key:t.compiled_task_prompt for t in detail.module_tasks}
    await BatchGenerationConfirmationService(f.repository,f.service.identity_provider).confirm_batch(f.project_id,batch.id,prompts,"retry-confirm")
    await f.repository.cancel_batch(batch.id,f.workspace_id)
    cancelled = await f.repository.get_batch_detail(batch.id,f.workspace_id)
    slot = cancelled.slots[0]
    before = cancelled.module_tasks[0]
    await f.repository.retry_slot(slot.id,f.workspace_id)
    retried = await f.repository.get_batch_detail(batch.id,f.workspace_id)
    assert retried.module_tasks[0].snapshot == before.snapshot
    assert retried.module_tasks[0].final_prompt == before.final_prompt
    assert not f.compiler.requests
from backend.app.core.errors import AppError

@pytest.mark.asyncio
async def test_regular_edited_parameters_change_prompt_and_cannot_reuse_compile_key():
    f = await hero_fixture()
    original = _input(f.source_asset_id)
    req = replace(original,creation_mode="regular",modules=[replace(original.modules[0],regular_task={"goal":"Material","copy":"Cotton"},module_parameters=[{"key":"Material","value":"Cotton"}])])
    first = await f.service.compile_prompt_batch(f.project_id,req,"edit-compile")
    edited = replace(req,modules=[replace(req.modules[0],regular_task={"goal":"Material detail","copy":"Linen"},module_parameters=[{"key":"Material","value":"Linen"}])])
    with pytest.raises(AppError) as error:
        await f.service.compile_prompt_batch(f.project_id,edited,"edit-compile")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    second = await f.service.compile_prompt_batch(f.project_id,edited,"edit-new")
    a = await f.repository.get_batch_detail(first.id,f.workspace_id)
    b = await f.repository.get_batch_detail(second.id,f.workspace_id)
    assert 'Cotton' in a.module_tasks[0].compiled_task_prompt
    assert 'Linen' in b.module_tasks[0].compiled_task_prompt
    assert 'Cotton' not in b.module_tasks[0].compiled_task_prompt
    confirmation = BatchGenerationConfirmationService(f.repository,f.service.identity_provider)
    with pytest.raises(AppError) as error:
        await confirmation.confirm_batch(f.project_id,second.id,{b.module_tasks[0].module_key:'override'},'bad-confirm')
    assert error.value.code == "BATCH_GENERATION_REGULAR_PROMPT_IMMUTABLE"

