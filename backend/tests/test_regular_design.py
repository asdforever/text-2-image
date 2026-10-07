import pytest
from types import SimpleNamespace

from backend.app.application.regular_design import regular_module_direction, regular_snapshot, regular_suite_consistency
from backend.app.application.suite_planning_service import SuitePlanCompilationInput, SuitePlanModuleInput
from backend.tests.test_suite_planning_service import _fixture as suite_fixture


def test_regular_suite_keeps_shared_identity_but_varies_each_module_direction():
    shared = regular_suite_consistency()
    scene = regular_module_direction("suite-scene")
    detail = regular_module_direction("suite-detail")
    spec = regular_module_direction("suite-spec")

    assert "同一商品" in shared
    assert "不要复制同一背景" in shared
    assert "产品出场时" in shared
    assert "不强行加入" in shared
    assert "完整静置产品图最多一张" in shared
    assert "真实桌面" in scene
    assert "产品出场契约" in scene
    assert "必须处于使用状态" in scene
    assert "局部微距" in detail
    assert "不得再次完整摆拍" in detail
    assert "参数表" in spec
    assert len({scene, detail, spec}) == 3


@pytest.mark.asyncio
async def test_regular_suite_compilation_puts_direction_into_each_frozen_prompt():
    fixture = await suite_fixture()
    request = SuitePlanCompilationInput(
        source_asset_ids=fixture.source_asset_ids,
        market_id="taobao",
        model_id="gpt-image-2-5",
        style_id="minimal",
        aspect_ratio="3:4",
        resolution="标准 1K",
        output_language="中文",
        creation_mode="regular",
        modules=[
            SuitePlanModuleInput("suite-scene", 1, [{"key": "场景", "value": "书房"}], regular_task={"goal": "展示使用", "copy": "真实使用"}),
            SuitePlanModuleInput("suite-spec", 1, [{"key": "重量", "value": "112g"}], regular_task={"goal": "展示参数", "copy": "轻巧"}),
        ],
    )

    plan = await fixture.service.compile_plan(fixture.project_id, request, "regular-direction-test")
    detail = await fixture.plans.get_plan_detail(plan.id, fixture.workspace_id, fixture.project_id)
    prompts = {item.module_key: item.compiled_task_prompt for item in detail.modules}

    assert "真实桌面" in prompts["suite-scene"]
    assert "参数表" in prompts["suite-spec"]
    assert "不要复制同一背景" in prompts["suite-scene"]
    assert "先判断产品是否需要出场" in prompts["suite-scene"]
    assert "具体行为或状态" in prompts["suite-scene"]
    assert "不能只写‘放在场景中’" in prompts["suite-scene"]
    assert "食用中" in prompts["suite-spec"]
    assert '"moduleId": "suite-spec"' in prompts["suite-scene"]
    assert "If the product appears" in prompts["suite-scene"]
    assert prompts["suite-scene"] != prompts["suite-spec"]


def test_regular_snapshot_passes_peer_modules_to_product_appearance_guidance():
    class Constraints:
        market = SimpleNamespace(content="平台规则")
        style = SimpleNamespace(content="风格规则")

        def to_snapshot(self):
            return {}

    request = SimpleNamespace(
        market_id="taobao", custom_style="", aspect_ratio="3:4",
        resolution="标准 1K", output_language="中文", user_notes="",
    )
    selected = SimpleNamespace(
        task_id="scene", module_id="suite-scene",
        regular_task={"goal": "展示使用", "copy": "真实使用"},
    )
    master = {
        "planningContractVersion": "regular-design-v1",
        "modules": [
            {"taskId": "scene", "moduleId": "suite-scene", "taskTitle": "使用场景", "reason": "展示使用", "suggestedCopy": "真实使用"},
            {"taskId": "mood", "moduleId": "suite-mood", "taskTitle": "氛围", "reason": "营造氛围", "suggestedCopy": "轻松"},
        ],
    }
    snapshot = regular_snapshot(
        request, selected, master,
        {"label": "使用场景图", "description": "真实使用"},
        [], {"label": "淘宝"}, {"id": "minimal"}, Constraints(),
    )

    assert '"moduleId": "suite-mood"' in snapshot["compiledTaskPrompt"]
