from backend.app.application.design_review import review_design_set


def test_review_flags_repeated_full_product_and_missing_evidence() -> None:
    result = review_design_set(
        {
            "modules": [
                {
                    "taskId": "hero-1",
                    "productPresence": "full",
                    "layoutFamily": "centered_hero",
                    "informationQuestion": "这是什么？",
                    "evidence": ["visible_product"],
                },
                {
                    "taskId": "hero-2",
                    "productPresence": "full",
                    "layoutFamily": "centered_hero",
                    "informationQuestion": "为什么值得买？",
                    "evidence": [],
                },
            ]
        },
        generated_metadata=[
            {"taskId": "hero-1", "camera": "front"},
            {"taskId": "hero-2", "camera": "front"},
        ],
    )

    assert "repeated_full_product_hero" in result.hard_failures
    assert "missing_required_evidence" in result.hard_failures
    assert result.total_score < 20
    assert any("detail" in reason for reason in result.actionable_reasons)


def test_review_flags_contrast_and_mobile_readability() -> None:
    result = review_design_set(
        {
            "modules": [
                {
                    "taskId": "detail-1",
                    "productPresence": "detail",
                    "layoutFamily": "detail_annotation",
                    "informationQuestion": "用户要看清哪个细节？",
                    "evidence": ["visible_detail"],
                }
            ]
        },
        generated_metadata=[
            {
                "taskId": "detail-1",
                "textContrastRatio": 2.8,
                "textReadableMobile": False,
            }
        ],
    )

    assert "unreadable_text" in result.hard_failures
    assert any("对比度" in reason or "移动端" in reason for reason in result.actionable_reasons)
