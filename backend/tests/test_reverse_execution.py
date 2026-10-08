from uuid import UUID
from copy import deepcopy

import pytest

from app.application.reverse_execution import build_execution_plan, compile_task_prompt


VERSION_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_descriptive_prompt_preserves_page_constraints_without_form_headings():
    task = {"title": "桌面场景", "parametersAssigned": True,
        "moduleParameters": [{"key": "尺寸", "value": "100×60mm"}],
        "structure": {
            "goal": "展示日常办公用途",
            "layout": "场景与空间：浅木桌面与后方白色杯子。\n主体数量：1；位置与占画比例：右下方，占宽度35%。\n相机机位：斜上方。\n产品朝向与长轴：前端朝左下，后端朝右上；前端(0.30, 0.70)，后端(0.60, 0.40)。\n可见面：顶面与近景侧壁。\n接触与投影：底部接触桌面，右侧柔和投影。\n观察依据：原图按键分缝。\n不确定项：无法测量精确角度。",
            "informationHierarchy": "第一层：主标题；第二层：商品。",
            "typography": "标题在左上方，深灰无衬线粗体，左对齐。",
            "colorAndLighting": "左侧自然光，浅木与暖白色系。",
            "adaptationNotes": "杯子高度不得超过商品两倍。",
        }}
    before = deepcopy(task)
    prompt = compile_task_prompt(task, {"商品名称": "有线鼠标", "全局资料": "未分配的宣传语"})
    for heading in ("当前商品事实：", "任务：", "场景与构图：", "主体数量：", "相机机位：", "目标：", "信息层级：", "字体与文字区域：", "色彩与光影：", "适配要求："):
        assert heading not in prompt
    for detail in ("有线鼠标", "100×60mm", "浅木桌面", "白色杯子", "右下方", "35%", "斜上方", "前端朝左下", "(0.30, 0.70)", "顶面与近景侧壁", "右侧柔和投影", "左对齐", "左侧自然光", "杯子高度不得超过商品两倍"):
        assert detail in prompt
    assert "未分配的宣传语" not in prompt
    assert "观察依据" not in prompt and "不确定项" not in prompt
    assert task == before


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
    assert "仅迁移已有场景、道具、光影和排版" in prompt
    assert "以输入商品图作为唯一外观参考" in prompt
    assert "不新增装饰" in prompt
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
    assert "按上述机位、朝向、可见面与占画比例重新摆放和拍摄商品" in prompt
    assert "不沿用输入图的拍摄姿态" in prompt
    assert "不通过镜像或二维旋转代替" in prompt
    assert "蓝白裂纹" in prompt
    assert "未描述的细节可合理设计" not in prompt


def test_scene_prompt_prioritizes_pose_and_integrates_product_into_one_photograph():
    layout = (
        "场景与空间：室内木质桌面，左侧窗户、左侧笔记本电脑和后方马克杯。\n"
        "主体数量：1；位置与占画比例：中下部偏右，占画面宽度三分之一。\n"
        "相机机位：侧前方斜上方，顶面与近景侧壁均可见。\n"
        "产品朝向与长轴：按键端朝画面左下，尾端朝画面右上。\n"
        "接触与投影：底部接触木质桌面，右侧柔和阴影。\n"
        "观察依据：参考鼠标的按键分缝可见。\n"
        "不确定项：无法测量精确俯仰角。"
    )
    task = {"title": "办公场景", "structure": {"layout": layout, "goal": "展示白色无线鼠标"}}
    original = task["structure"]["layout"]
    prompt = compile_task_prompt(task, {"商品名称": "蓝白有线鼠标"})

    assert prompt.index("按键端朝画面左下") < prompt.index("画面的内容职责")
    assert prompt.index("蓝白有线鼠标") < prompt.index("展示白色无线鼠标")
    assert "商品与场景共用同一相机透视" in prompt
    assert "受光、反射、景深与环境一致" in prompt
    assert "有接触的支撑处生成贴合的阴影" in prompt
    assert "有线商品保留线缆，从真实连接点自然弯曲" in prompt
    assert "不擅自放大主体或改换可见侧面" in prompt
    assert "观察依据：" not in prompt
    assert "不确定项：" not in prompt
    assert task["structure"]["layout"] == original


def test_explicit_closeup_and_floating_layout_is_not_overridden_by_scene_contact_rules():
    layout = "产品前景特写，主体占画面宽度80%，按设计倾斜悬浮，背景是一张木质桌面。"
    prompt = compile_task_prompt({"structure": {"layout": layout}})
    assert layout in prompt
    assert "不得把商品放大成前景特写" not in prompt
    assert "不倾斜悬浮" not in prompt
    assert "有接触的支撑处生成贴合的阴影" in prompt
    assert "悬浮或夹持时保留原支撑关系" in prompt


def test_side_clamp_and_noncontact_bottom_are_not_reinterpreted_as_ground_contact():
    layout = "商品由夹具支撑，底部不接触桌面，侧面接触夹具。"
    prompt = compile_task_prompt({"structure": {"layout": layout}})
    assert layout in prompt
    assert "有接触的支撑处生成贴合的阴影" in prompt
    assert "商品底面与实际支撑面吻合" not in prompt
