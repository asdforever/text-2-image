import json
from pathlib import Path

import pytest

from backend.app.core.errors import AppError


EXPECTED_GUIDES = [
    "commerce-core",
    "visual-hierarchy",
    "data-explanation",
    "usage-context",
]


def test_full_context_is_traceable_and_stable():
    from backend.app.application.commerce_design import commerce_design_context

    first = commerce_design_context()
    second = commerce_design_context()

    assert first["version"] == "commerce-design-v1"
    assert [guide["id"] for guide in first["guides"]] == EXPECTED_GUIDES
    assert len(first["contentSha256"]) == 64
    assert first["contentSha256"] == second["contentSha256"]
    assert {
        (source["repository"], source["revision"])
        for source in first["sources"]
    } == {
        ("nextlevelbuilder/ui-ux-pro-max-skill", "09170eec67eefd46a7ae85de61b40c194020f997"),
        ("pbakaus/impeccable", "9d715cc4f5564a990ca8345abfdd5df6dc9b41c8"),
    }


def test_selected_context_keeps_core_and_requested_order():
    from backend.app.application.commerce_design import commerce_design_context

    full = commerce_design_context()
    selected = commerce_design_context(["usage-context", "data-explanation"])

    assert [guide["id"] for guide in selected["guides"]] == [
        "commerce-core",
        "usage-context",
        "data-explanation",
    ]
    assert selected["contentSha256"] == full["contentSha256"]


@pytest.mark.parametrize(
    "guide_ids",
    [
        ["unknown-guide"],
        ["commerce-core"],
        ["visual-hierarchy", "visual-hierarchy"],
        ["visual-hierarchy", "data-explanation", "usage-context"],
        [["data-explanation"]],
        [None],
    ],
)
def test_invalid_selection_is_rejected(guide_ids):
    from backend.app.application.commerce_design import commerce_design_context

    with pytest.raises(AppError) as caught:
        commerce_design_context(guide_ids)

    assert caught.value.code == "DESIGN_GUIDE_INVALID"
    assert caught.value.status_code == 422


def test_returned_values_are_isolated_from_cached_bundle():
    from backend.app.application.commerce_design import commerce_design_context, load_commerce_design

    loaded = load_commerce_design()
    selected = commerce_design_context(["data-explanation"])
    loaded["sources"].clear()
    loaded["guides"][0]["rules"].clear()
    selected["guides"].clear()

    reloaded = load_commerce_design()
    reselected = commerce_design_context(["data-explanation"])
    assert reloaded["sources"]
    assert reloaded["guides"][0]["rules"]
    assert [guide["id"] for guide in reselected["guides"]] == [
        "commerce-core",
        "data-explanation",
    ]


@pytest.mark.parametrize("failure", ["missing", "malformed", "invalid_schema"])
def test_unavailable_bundle_fails_closed(monkeypatch, tmp_path: Path, failure: str):
    from backend.app.application import commerce_design

    bundle = tmp_path / "commerce_design_v1"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps({"version": "commerce-design-v1", "sources": []}), encoding="utf-8"
    )
    if failure == "malformed":
        (bundle / "guides.json").write_text("{", encoding="utf-8")
    elif failure == "invalid_schema":
        (bundle / "guides.json").write_text(json.dumps({"guides": []}), encoding="utf-8")

    monkeypatch.setattr(commerce_design, "_BUNDLE", bundle)
    commerce_design._load_bundle.cache_clear()
    try:
        with pytest.raises(AppError) as caught:
            commerce_design.load_commerce_design()
        assert caught.value.code == "COMMERCE_DESIGN_UNAVAILABLE"
        assert caught.value.status_code == 503
    finally:
        commerce_design._load_bundle.cache_clear()
