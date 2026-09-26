import json
from pathlib import Path

from backend.app.application.design_review import review_design_set


def test_general_design_rules_cover_multiple_categories() -> None:
    path = Path(__file__).parent / "fixtures" / "general_design_cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))

    assert {case["category"] for case in cases} == {"electronics", "home_goods", "beauty_packaging"}
    for case in cases:
        result = review_design_set(case)
        assert "missing_required_evidence" not in result.hard_failures
        assert "repeated_full_product_hero" not in result.hard_failures
        assert result.total_score >= 15
