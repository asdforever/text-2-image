from uuid import UUID

import pytest

from app.application.reverse_execution import build_execution_plan, compile_task_prompt


VERSION_ID = UUID("11111111-1111-1111-1111-111111111111")


def reference(reference_id: str, ordinal: int) -> dict:
    return {
        "id": reference_id,
        "ordinal": ordinal,
        "filename": f"template-{ordinal}.png",
        "previewUrl": f"/preview/{reference_id}",
    }


def test_build_plan_creates_one_ordered_task_per_reference_and_matches_modules():
    document = {
        "references": [reference("ref-2", 2), reference("ref-1", 1)],
        "overall": {"visualSystem": "暖白背景、柔和侧光"},
        "modules": [
            {
                "id": "module-1",
                "title": "首屏主视觉",
                "referenceImageId": "ref-1",
                "goal": "建立第一眼认知",
                "layout": "产品居中偏右",
                "informationHierarchy": "品牌名优先",
                "typography": "左侧留白放标题",
                "colorAndLighting": "暖白柔光",
                "adaptationNotes": "替换为当前商品事实",
            }
        ],
    }

    plan = build_execution_plan(document, VERSION_ID)

    assert [item["referenceImageId"] for item in plan["tasks"]] == ["ref-1", "ref-2"]
    assert len(plan["tasks"]) == 2
    assert plan["tasks"][0]["referenceModuleId"] == "module-1"
    assert plan["tasks"][1]["referenceModuleId"] is None
    assert plan["tasks"][1]["structure"]["layout"] == ""


def test_compile_task_prompt_keeps_template_structure_and_replaces_product_facts():
    task = {
        "title": "首屏主视觉",
        "structure": {
            "goal": "建立第一眼认知",
            "layout": "产品居中偏右",
            "informationHierarchy": "品牌名优先",
            "typography": "左侧留白放标题",
            "colorAndLighting": "暖白柔光",
            "adaptationNotes": "替换为当前商品事实",
        },
    }

    prompt = compile_task_prompt(task, {"商品名称": "蓝牙鼠标", "核心卖点": "静音点击"})

    assert "产品居中偏右" in prompt
    assert "左侧留白放标题" in prompt
    assert "蓝牙鼠标" in prompt
    assert "静音点击" in prompt
    assert "保持模板结构" in prompt
    assert "输入图片只用于确认当前商品" in prompt
    assert "按拆解描述重新生成场景与道具" in prompt
    assert "严格保持参考图" not in prompt
    assert "只替换商品内容" not in prompt


def test_task_parameters_limit_facts_to_this_image_and_apply_output_language():
    task = {"title": "尺寸图", "structure": {}, "moduleParameters": [{"key": "尺寸", "value": "100×60mm"}], "parametersAssigned": True}
    prompt = compile_task_prompt(task, {"商品名称": "鼠标", "全局资料": "静音按键、两年保修"}, {"outputLanguage": "英文"})
    assert "100×60mm" in prompt
    assert "鼠标" in prompt
    assert "静音按键" not in prompt
    assert "两年保修" not in prompt
    assert "英文" in prompt

    task["moduleParameters"] = []
    prompt = compile_task_prompt(task, {"全局资料": "两年保修"})
    assert "两年保修" not in prompt


@pytest.mark.parametrize("layout", [
    "低机位前侧三分之四视角；按键端朝画面左下，尾部朝右上；顶面与侧壁同时可见，主体居中偏下。",
    "接近水平的正侧面视角；按键端朝画面左侧，尾部朝右侧；侧壁为主，顶面仅露窄条。",
])
def test_compiled_prompt_uses_each_task_pose_instead_of_product_photo_pose(layout):
    prompt = compile_task_prompt(
        {"title": "产品展示", "structure": {"layout": layout}},
        {"商品名称": "蓝白有线鼠标", "颜色": "蓝白裂纹"},
    )

    assert layout in prompt
    assert "机位与产品姿态以场景与构图中的拆解描述为准" in prompt
    assert "不得沿用商品输入图的拍摄角度和摆放方向" in prompt
    assert "主体数量、画面位置、占画比例、留白、裁切和遮挡关系" in prompt
    assert "不得通过镜像翻转商品" in prompt
    assert "蓝白裂纹" in prompt
    assert "未描述的细节可合理设计" not in prompt
