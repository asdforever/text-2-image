import json
from uuid import UUID

import pytest

from backend.app.application.module_planning_service import ModulePlanInput
from backend.app.application.module_planning_v2 import build_v2_compiler_prompts, resolve_style_seed
from backend.tests.test_module_planning import fixture
from backend.tests.test_suite_planning_service import SuitePlanCompilationInput, SuitePlanModuleInput


def new_output(mode):
    return {"planningContractVersion": "commerce-design-v1", "sharedVisualDirection": "大数字与简洁线条统一层级",
            "summary": "解释已确认参数", "modules": [{
                "taskId": "rate", "taskTitle": "解释回报率", "moduleId": f"{mode}-freeform",
                "resultCount": 1, "moduleParameters": [{"key": "主信息", "value": "1000 Hz"}],
                "compositionBrief": "大数字配等间隔概念刻度，不出现产品", "reason": "解释参数含义",
                "informationQuestion": "回报率表示什么", "productPresence": "none",
                "designGuideIds": ["data-explanation"], "styleTemplateId": "infographic-engine",
                "bigIdea": "读懂报告频率", "visualMechanism": "大数字与刻度对应",
            }], "warnings": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hero", "suite"])
async def test_master_uses_actual_knowledge_style_and_freeform_catalog(mode):
    f = await fixture(mode)
    f.master.result = new_output(mode)
    payload = ModulePlanInput(**{**f.input.model_dump(), "styleId": "minimal", "customStyle": "标题醒目"})
    result = await f.master_service.plan(f.project_id, payload, "design-master")
    actual = json.loads(f.master.calls[0].user_prompt)
    assert actual["designKnowledge"] == result["snapshot"]["designKnowledge"]
    assert actual["commerceDesign"] == result["snapshot"]["commerceDesign"]
    assert actual["selectedStyle"]["id"] == "minimal"
    assert actual["selectedStyle"]["customStyle"] == "标题醒目"
    assert f"{mode}-freeform" in [m["id"] for m in actual["moduleCatalog"]]
    assert result["modules"][0]["moduleParameters"] == [{"key": "主信息", "value": "1000 Hz"}]
    assert len(f.master.calls) == 1


def test_compiler_separates_advice_from_explicit_composition_and_copy():
    _, user, snapshot = build_v2_compiler_prompts(
        seed=resolve_style_seed({"id": "minimal"}),
        module={"id": "hero-freeform", "mode": "hero"},
        module_parameters=[{"key": "构图要求", "value": "标题放左上角"}, {"key": "主信息", "value": "1000 Hz"}],
        custom_style="", task_outline=new_output("hero")["modules"][0],
        market={"id": "taobao"}, output={}, constraints={},
        shared_visual_direction="统一大字层级", placement="gallery",
    )
    context = json.loads(user)
    assert context["taskOutline"]["productPresence"] == "none"
    assert context["explicitCompositionRequirements"] == ["标题放左上角"]
    assert context["moduleParameters"] == [{"key": "主信息", "value": "1000 Hz"}]
    assert context["placement"] == "gallery"
    assert context["sharedVisualDirection"] == "统一大字层级"
    assert [g["id"] for g in context["commerceDesign"]["guides"]] == ["commerce-core", "data-explanation"]
    assert snapshot["commerceDesign"] == context["commerceDesign"]


@pytest.mark.asyncio
async def test_suite_freeform_reaches_single_image_compiler():
    f = await fixture("suite")
    f.master.result = new_output("suite")
    payload = ModulePlanInput(**{**f.input.model_dump(), "styleId": "minimal", "customStyle": ""})
    master = await f.master_service.plan(f.project_id, payload, "suite-design")
    f.service.module_planning = f.master_service
    request = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids, market_id="taobao",
        model_id="gpt-image-2-5", style_id="minimal", aspect_ratio="3:4", resolution="标准 1K",
        output_language="中文", module_plan_id=UUID(master["id"]),
        modules=[SuitePlanModuleInput("suite-freeform", 1, [{"key": "主信息", "value": "1000 Hz"}], "rate")])
    await f.service.compile_plan(f.project_id, request, "suite-design-compile")
    context = json.loads(f.compiler.requests[0].user_prompt)
    assert context["taskOutline"]["taskTitle"] == "解释回报率"
    assert context["placement"] == "detail"
    assert context["sharedVisualDirection"] == "大数字与简洁线条统一层级"


@pytest.mark.asyncio
async def test_pending_plan_is_identified_before_model_completes():
    f = await fixture("hero")
    f.master.result = new_output("hero")
    original = f.master.plan_modules

    async def inspect(request):
        pending = await f.master_service.latest(f.project_id, "hero")
        assert pending["status"] == "planning"
        assert pending["planningContractVersion"] == "commerce-design-v1"
        return await original(request)

    f.master.plan_modules = inspect
    await f.master_service.plan(f.project_id, f.input, "pending-contract")


@pytest.mark.asyncio
async def test_hero_freeform_tasks_keep_identity_placement_and_user_edits():
    from copy import deepcopy
    from dataclasses import replace

    from backend.app.application.batch_generation_service import BatchHeroModuleInput
    from backend.app.application.module_planning_service import ModulePlanningService
    from backend.app.module_planning_repository import MemoryModulePlanningRepository
    from backend.tests.test_batch_generation_compile_service import _fixture, _input
    from backend.tests.test_module_planning import Planner

    f = await _fixture()
    output = new_output("hero")
    second = deepcopy(output["modules"][0])
    second.update(taskId="rate-second", taskTitle="理解使用场景")
    output["modules"].append(second)
    planner = Planner(output)
    master_service = ModulePlanningService(
        MemoryModulePlanningRepository(), f.projects, f.storage, f.config, f.prompts,
        f.service.identity_provider, planner,
    )
    master = await master_service.plan(f.project_id, ModulePlanInput(
        mode="hero", sourceAssetIds=[f.source_asset_id], marketId="taobao",
        aspectRatio="1:1", outputLanguage="中文", brief="解释回报率及用途",
        styleId="precision", customStyle="保持冷灰背景",
    ), "hero-freeform-master")
    f.service.module_planning = master_service
    request = replace(_input(f.source_asset_id), module_plan_id=UUID(master["id"]), modules=[
        BatchHeroModuleInput("hero-freeform", 1, [{"key": "构图要求", "value": "标题放左上角"}], "rate"),
        BatchHeroModuleInput("hero-freeform", 1, [{"key": "构图要求", "value": "标题放右上角"}], "rate-second"),
    ])
    batch = await f.service.compile_prompt_batch(f.project_id, request, "hero-freeform-compile")
    detail = await f.repository.get_batch_detail(batch.id, f.workspace_id)
    contexts = [json.loads(call.user_prompt) for call in f.compiler.requests]
    assert [c["placement"] for c in contexts] == ["primary", "gallery"]
    assert [c["taskOutline"]["taskId"] for c in contexts] == ["rate", "rate-second"]
    assert [c["explicitCompositionRequirements"] for c in contexts] == [["标题放左上角"], ["标题放右上角"]]
    assert all(c["taskOutline"]["productPresence"] == "none" for c in contexts)
    assert all(c["sharedVisualDirection"] == output["sharedVisualDirection"] for c in contexts)
    assert [(t.module_key, t.requested_image_count) for t in detail.module_tasks] == [("rate", 1), ("rate-second", 1)]
    assert detail.slots == []
    assert f.editor.edit_requests == []
    assert len(planner.calls) == 1
    assert len(f.compiler.requests) == 2
