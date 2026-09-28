import json

from backend.app.application.module_planning_service import MasterOutput
from backend.app.application.module_planning_v2 import (
    build_v2_compiler_prompts,
    resolve_style_seed,
)


def test_master_output_preserves_set_and_task_visual_constraints() -> None:
    value = MasterOutput.model_validate(
        {
            "planningContractVersion": "commerce-design-v1",
            "sharedVisualDirection": "统一品牌色和清晰的信息层级。",
            "summary": "先建立识别，再解释差异。",
            "visualRhythm": ["full_bleed", "detail_callout"],
            "productPresencePlan": ["full", "detail"],
            "layoutFamilies": ["centered_hero", "grid_callout"],
            "modules": [
                {
                    "moduleId": "suite-detail",
                    "taskId": "detail-1",
                    "taskTitle": "解释关键细节",
                    "designGuideIds": ["visual-hierarchy", "data-explanation"],
                    "resultCount": 1,
                    "moduleParameters": [],
                    "compositionBrief": "只表现关键局部和标注关系。",
                    "reason": "回答细节问题。",
                    "informationQuestion": "用户要看清哪个细节？",
                    "productPresence": "detail",
                    "subjectScale": "medium",
                    "layoutFamily": "detail_annotation",
                    "evidence": ["visible_product_detail"],
                    "previousModuleContrast": "不重复完整商品主视觉。",
                    "avoid": ["repeat_previous_angle"],
                    "styleTemplateId": "infographic-engine",
                    "visualStyleTags": ["Infographic"],
                    "sceneTags": ["Tech"],
                    "referenceCaseIds": [334],
                    "bigIdea": "用局部结构解释关键差异。",
                    "visualMechanism": "局部放大与整体定位形成对应。",
                }
            ],
            "warnings": [],
        }
    )

    assert value.visualRhythm == ["full_bleed", "detail_callout"]
    assert value.modules[0].productPresence == "detail"
    assert value.modules[0].informationQuestion == "用户要看清哪个细节？"
    assert value.modules[0].styleTemplateId == "infographic-engine"
    assert value.modules[0].referenceCaseIds == [334]
    assert value.modules[0].visualMechanism == "局部放大与整体定位形成对应。"


def test_compiler_prompt_contains_generic_design_knowledge() -> None:
    seed = resolve_style_seed({"id": "minimal"})
    _system, user, _snapshot = build_v2_compiler_prompts(
        seed=seed,
        module={"id": "suite-detail", "mode": "suite", "label": "商品细节图"},
        module_parameters=[],
        custom_style="",
        task_outline={
            "designGuideIds": ["visual-hierarchy"],
            "productPresence": "detail",
            "layoutFamily": "detail_annotation",
            "informationQuestion": "用户要看清哪个细节？",
        },
        market={"id": "market", "label": "通用电商"},
        output={"aspectRatio": "3:4", "resolution": "标准 1K", "language": "中文"},
        constraints={"productAuthenticity": "只依据源图", "market": "通用规则"},
    )

    context = json.loads(user)
    assert context["designKnowledge"]["version"] == "v1"
    assert "detail" in context["designKnowledge"]["productPresenceValues"]
    assert "layoutFamily" in context["taskOutline"]
    assert context["styleLibrary"]["version"]
    assert context["styleLibrary"]["templates"]
