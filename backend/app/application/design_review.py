from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .design_knowledge import load_design_knowledge


class DesignReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_version: str
    knowledge_sha256: str
    hard_failures: list[str] = Field(default_factory=list)
    category_scores: dict[str, int] = Field(default_factory=dict)
    total_score: int = Field(ge=0, le=20)
    actionable_reasons: list[str] = Field(default_factory=list)


def review_design_set(
    plans: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    generated_metadata: Sequence[Mapping[str, Any]] | None = None,
) -> DesignReviewResult:
    """Run deterministic, metadata-first design checks.

    Pixel inspection is intentionally optional in v1. Generators can provide camera,
    contrast and mobile-readability metadata; missing metadata never invents a failure.
    """
    pack = load_design_knowledge()
    modules = _modules(plans)
    metadata_by_task = {
        str(item.get("taskId") or item.get("moduleId") or ""): item
        for item in (generated_metadata or [])
        if isinstance(item, Mapping)
    }
    failures: list[str] = []
    reasons: list[str] = []

    full_indices = [
        index for index, module in enumerate(modules)
        if str(module.get("productPresence", "")).strip() == "full"
    ]
    repeated_full = False
    for left, right in zip(full_indices, full_indices[1:]):
        left_layout = str(modules[left].get("layoutFamily", ""))
        right_layout = str(modules[right].get("layoutFamily", ""))
        left_meta = _metadata_for(modules[left], metadata_by_task)
        right_meta = _metadata_for(modules[right], metadata_by_task)
        same_camera = left_meta.get("camera") and left_meta.get("camera") == right_meta.get("camera")
        if right == left + 1 and (left_layout == right_layout or same_camera):
            repeated_full = True
            break
    if repeated_full:
        failures.append("repeated_full_product_hero")
        reasons.append("连续两张都完整展示商品且复用同一构图/机位；下一张改用 detail/局部、情境或结构证据。")

    repeated_layout = False
    for left, right in zip(modules, modules[1:]):
        if left.get("layoutFamily") and left.get("layoutFamily") == right.get("layoutFamily"):
            repeated_layout = True
            break
        left_meta = _metadata_for(left, metadata_by_task)
        right_meta = _metadata_for(right, metadata_by_task)
        if left_meta.get("camera") and left_meta.get("camera") == right_meta.get("camera"):
            repeated_layout = True
            break
    if repeated_layout:
        failures.append("repeated_camera_or_layout")
        reasons.append("相邻图片复用相同版式或机位；至少改变主体尺度、背景、版式或商品出场方式。")

    missing_evidence = [
        str(module.get("taskId") or module.get("moduleId") or index + 1)
        for index, module in enumerate(modules)
        if str(module.get("informationQuestion", "")).strip()
        and not _nonempty_list(module.get("evidence"))
    ]
    if missing_evidence:
        failures.append("missing_required_evidence")
        reasons.append(f"任务 {', '.join(missing_evidence)} 没有绑定可验证证据；补充源图可见事实或资料依据。")

    contrast_low = False
    mobile_low = False
    for module in modules:
        metadata = _metadata_for(module, metadata_by_task)
        ratio = metadata.get("textContrastRatio", metadata.get("contrastRatio"))
        if isinstance(ratio, (int, float)) and ratio < 4.5:
            contrast_low = True
        if metadata.get("textReadableMobile") is False:
            mobile_low = True
        min_size = metadata.get("minTextSizePx")
        if isinstance(min_size, (int, float)) and min_size < 12:
            mobile_low = True
    if contrast_low or mobile_low:
        failures.append("unreadable_text")
        details = []
        if contrast_low:
            details.append("提高文字与背景对比度（建议至少 4.5:1）")
        if mobile_low:
            details.append("放大移动端最小字号并减少文字密度")
        reasons.append("；".join(details) + "。")

    scores = {
        "hierarchy": _score_hierarchy(modules),
        "rhythm": _score_rhythm(modules),
        "evidence": 5 if not missing_evidence else max(0, 5 - len(missing_evidence)),
        "readability": 5 if not (contrast_low or mobile_low) else 2,
    }
    return DesignReviewResult(
        knowledge_version=pack.version,
        knowledge_sha256=pack.rules_sha256,
        hard_failures=failures,
        category_scores=scores,
        total_score=sum(scores.values()),
        actionable_reasons=reasons,
    )


def _modules(plans: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(plans, Mapping):
        value = plans.get("modules", [])
    else:
        value = plans
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _metadata_for(module: Mapping[str, Any], by_task: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    key = str(module.get("taskId") or module.get("moduleId") or "")
    return by_task.get(key, {})


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and any(str(item).strip() for item in value)


def _score_hierarchy(modules: Sequence[Mapping[str, Any]]) -> int:
    if not modules:
        return 0
    return min(5, sum(1 for module in modules if str(module.get("informationQuestion", "")).strip()))


def _score_rhythm(modules: Sequence[Mapping[str, Any]]) -> int:
    if len(modules) < 2:
        return 5 if modules else 0
    presence = [str(module.get("productPresence", "")) for module in modules]
    layouts = [str(module.get("layoutFamily", "")) for module in modules]
    score = 5
    if len(set(presence)) == 1:
        score -= 2
    if len(set(layouts)) == 1:
        score -= 2
    return max(0, score)
