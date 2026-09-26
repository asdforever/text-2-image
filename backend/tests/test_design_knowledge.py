from backend.app.application.design_knowledge import (
    DesignImagePlan,
    DesignSetPlan,
    load_design_knowledge,
)


def test_load_design_knowledge_v1_exposes_generic_set_and_image_rules() -> None:
    pack = load_design_knowledge()

    assert pack.version == "v1"
    assert pack.rules_sha256
    assert "hierarchy" in pack.principles
    assert "overview" in pack.narrative_stages
    assert "centered_hero" in pack.layout_families
    assert "full" in pack.product_presence_values
    assert "detail" in pack.product_presence_values


def test_design_plans_require_buyer_question_and_visual_contrast() -> None:
    plan = DesignSetPlan(
        narrative_stages=["overview", "feature"],
        visual_rhythm=["full_bleed", "detail_callout"],
        product_presence_plan=["full", "detail"],
        layout_families=["centered_hero", "grid_callout"],
    )
    image = DesignImagePlan(
        sequence=2,
        page_role="detail",
        narrative_stage="feature",
        information_question="用户要看清哪个差异点？",
        product_presence="detail",
        subject_scale="medium",
        camera="macro",
        layout_family="grid_callout",
        focal_point="feature",
        previous_module_contrast="不重复上一张的完整商品主视觉",
        evidence=["visible_product_detail"],
        avoid=["repeat_previous_angle"],
    )

    assert plan.product_presence_plan[-1] == "detail"
    assert image.product_presence == "detail"
    assert image.information_question
    assert image.previous_module_contrast
