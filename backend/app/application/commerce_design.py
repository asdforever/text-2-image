"""Load the versioned, application-owned commerce design guidance bundle."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from ..core.errors import AppError


_BUNDLE = Path(__file__).resolve().parents[1] / "data" / "commerce_design_v1"
_CORE_ID = "commerce-core"
_AUXILIARY_IDS = {"visual-hierarchy", "data-explanation", "usage-context"}
_EXPECTED_IDS = [_CORE_ID, "visual-hierarchy", "data-explanation", "usage-context"]


def _unavailable() -> AppError:
    return AppError(
        "COMMERCE_DESIGN_UNAVAILABLE",
        "电商设计指导不可用，请联系管理员",
        503,
    )


def _validate_bundle(manifest: Any, guide_document: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("version") != "commerce-design-v1":
        raise ValueError("invalid manifest")
    sources = manifest.get("sources")
    guides = guide_document.get("guides") if isinstance(guide_document, dict) else None
    if not isinstance(sources, list) or not sources or not isinstance(guides, list):
        raise ValueError("missing bundle records")
    if [guide.get("id") for guide in guides if isinstance(guide, dict)] != _EXPECTED_IDS:
        raise ValueError("invalid guide catalog")
    for source in sources:
        if not isinstance(source, dict) or not all(
            isinstance(source.get(key), str) and source[key].strip()
            for key in ("repository", "revision", "paths", "license")
        ):
            raise ValueError("invalid source")
    for guide in guides:
        rules = guide.get("rules")
        if not isinstance(rules, list) or not rules or not all(
            isinstance(rule, str) and rule.strip() for rule in rules
        ):
            raise ValueError("invalid guide")
    if sum(len(rule) for guide in guides for rule in guide["rules"]) > 6000:
        raise ValueError("guidance is too large")
    return {"version": manifest["version"], "sources": sources, "guides": guides}


@lru_cache(maxsize=1)
def _load_bundle() -> dict[str, Any]:
    try:
        raw_manifest = (_BUNDLE / "manifest.json").read_text(encoding="utf-8")
        raw_guides = (_BUNDLE / "guides.json").read_text(encoding="utf-8")
        manifest = json.loads(raw_manifest)
        guide_document = json.loads(raw_guides)
        bundle = _validate_bundle(manifest, guide_document)
        canonical = json.dumps(
            {"manifest": manifest, "guides": guide_document},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        bundle["contentSha256"] = sha256(canonical).hexdigest()
        return bundle
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise _unavailable() from None


def load_commerce_design() -> dict[str, Any]:
    """Return an independent copy of the complete validated guidance bundle."""
    return deepcopy(_load_bundle())


def commerce_design_context(guide_ids: list[str] | None = None) -> dict[str, Any]:
    """Return all guides, or the core guide plus up to two requested auxiliaries."""
    bundle = _load_bundle()
    if guide_ids is None:
        return deepcopy(bundle)
    if (
        not isinstance(guide_ids, list)
        or len(guide_ids) > 2
        or any(not isinstance(guide_id, str) or guide_id not in _AUXILIARY_IDS for guide_id in guide_ids)
        or len(set(guide_ids)) != len(guide_ids)
    ):
        raise AppError("DESIGN_GUIDE_INVALID", "设计指南选择无效", 422)

    by_id = {guide["id"]: guide for guide in bundle["guides"]}
    selected = [by_id[_CORE_ID], *(by_id[guide_id] for guide_id in guide_ids)]
    return deepcopy({**bundle, "guides": selected})
