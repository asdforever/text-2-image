from copy import deepcopy
from uuid import uuid4

from backend.app.application.reverse_execution import build_execution_plan, compile_task_prompt
from backend.app.application.reverse_image_analysis import ReferenceImageObservation, observed_layout
from backend.tests.test_reverse_projects import observation_result
from backend.app.application.reference_content_policy import clean_reference_text


def test_watermark_filter_keeps_negative_instructions_and_product_branding():
    clean = "黑色背景，产品居中，无水印。"
    branding = "保留当前商品壳体上的实体Logo，不得当作水印删除。"
    assert clean_reference_text(clean) == clean
    assert clean_reference_text(branding) == branding


def test_mixed_watermark_sentence_keeps_independent_background_and_product_constraints():
    text = "纯黑背景，产品居中，背后有半透明JD.COM京东水印，位于主体下方，文字在顶部。"
    cleaned = clean_reference_text(text)
    assert "JD.COM" not in cleaned and "水印" not in cleaned
    assert "纯黑背景" in cleaned and "产品居中" in cleaned
    assert "文字在顶部" in cleaned
    assert "位于主体下方" not in cleaned


def test_unrelated_negation_does_not_allow_positive_watermark_description():
    for text in (
        "背景叠加JD.COM京东水印不应遮挡商品主体。",
        "黑色背景无纹理但带有半透明JD.COM京东水印。",
    ):
        assert "JD.COM" not in clean_reference_text(text)


def test_observed_layout_excludes_platform_watermark_and_keeps_pose_and_background():
    raw = observation_result("reference")
    raw["sceneLayout"] = (
        "背景为深黑至近黑的暗色摄影背景，无环境道具；"
        "下部为半透明暗红色JD.COM京东水印及参数表格文字区；"
        "鼠标置于深色反光台面上。"
    )
    raw["productPresentation"]["framingAndOcclusion"] = (
        "鼠标主体完整呈现；线材向左延伸并在画面左缘被裁切；"
        "画面中部偏下有半透明JD.COM京东水印，未遮挡鼠标关键部件。"
    )
    layout = observed_layout(ReferenceImageObservation.model_validate(raw))
    assert "JD.COM" not in layout and "京东" not in layout
    assert "背景为深黑至近黑" in layout
    assert "深色反光台面" in layout
    assert "按键端朝画面左下" in layout
    assert "线材向左延伸" in layout


def test_execution_import_and_compile_exclude_overlay_instructions_but_keep_real_product_logo():
    document = {"references": [{"id":"reference", "ordinal":1}], "modules":[{
        "id":"specs", "referenceImageId":"reference", "title":"规格表",
        "goal":"展示产品参数",
        "layout":"纯黑背景；画面下部为半透明JD.COM京东水印；主体完整呈现。",
        "informationHierarchy":"第一层：标题；第二层：参数表；第三层：店铺Logo水印。",
        "typography":"无衬线字体；右下角叠加 photographer watermark © Acme。",
        "colorAndLighting":"柔光；背后放置电商平台标识。",
        "adaptationNotes":"保留当前商品壳体上的实体Logo；保持按键位置。",
    }]}
    original=deepcopy(document)
    task=build_execution_plan(document,uuid4())["tasks"][0]
    assert "JD.COM" not in task["structure"]["layout"]
    assert "watermark" not in task["structure"]["typography"]
    prompt=compile_task_prompt(task,{"商品名称":"我的鼠标", "真实品牌":"ACME Logo印在壳体尾部"})
    assert "JD.COM" not in prompt and "京东" not in prompt
    assert "第三层：店铺Logo水印" not in prompt
    assert "电商平台标识" not in prompt
    assert "ACME Logo印在壳体尾部" in prompt
    assert "保留当前商品壳体上的实体Logo" in prompt
    assert "参数表" in prompt and "无衬线字体" in prompt
    assert "不生成参考图中的平台、店铺或版权水印" in prompt
    assert document==original
