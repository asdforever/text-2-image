import json
import pytest

from backend.app.application.image_style_library import (
    STYLE_LIBRARY_SOURCE,
    resolve_style_template,
    style_library_context,
)


def test_style_library_exposes_generic_template_catalog() -> None:
    context = style_library_context()

    assert context["source"] == STYLE_LIBRARY_SOURCE
    assert context["version"]
    ids = {item["id"] for item in context["templates"]}
    assert {"product-commerce-visual", "infographic-engine", "poster-layout-system"} <= ids
    assert all(item["guidance"] and item["pitfalls"] for item in context["templates"])


def test_style_template_resolution_is_deterministic_and_unknown_ids_fail() -> None:
    template = resolve_style_template("product-commerce-visual")
    assert template["category"] == "Products & E-commerce"
    assert "Commerce" in template["scenes"]

    try:
        resolve_style_template("does-not-exist")
    except KeyError as exc:
        assert str(exc).strip("'") == "does-not-exist"
    else:
        raise AssertionError("unknown style template must fail")


def test_style_library_context_is_json_safe() -> None:
    json.dumps(style_library_context(), ensure_ascii=False)


def test_selected_template_loads_original_guidance_and_body_without_other_templates():
    context = style_library_context("infographic-engine")
    assert [t["id"] for t in context["templates"]] == ["infographic-engine"]
    assert "Urban Metabolism" in context["templates"][0]["promptTemplate"]
    assert context["revision"] == "0dc09c46c8a30b1fdd89c18cc78a894dac2104e3"
    assert len(context["contentSha256"]) == 64
    assert "ui-screenshot-system" in {t["id"] for t in style_library_context()["templates"]}


def test_returned_template_mutation_does_not_change_next_request():
    first = resolve_style_template("infographic-engine")
    first["guidance"].clear()
    assert resolve_style_template("infographic-engine")["guidance"]


def test_selected_unknown_template_is_not_silently_replaced():
    with pytest.raises(KeyError):
        style_library_context("unknown")


def test_every_imported_template_has_resolvable_original_text():
    for template in style_library_context()["templates"]:
        assert resolve_style_template(template["id"])["promptTemplate"].strip()
