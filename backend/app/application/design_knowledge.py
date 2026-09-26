from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


_KNOWLEDGE_PATH = Path(__file__).resolve().parents[1] / "data" / "design_knowledge_v1.json"


class DesignKnowledgePack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    principles: tuple[str, ...] = Field(min_length=1)
    narrative_stages: tuple[str, ...] = Field(min_length=1)
    layout_families: tuple[str, ...] = Field(min_length=1)
    product_presence_values: tuple[str, ...] = Field(min_length=1)
    subject_scale_values: tuple[str, ...] = Field(min_length=1)
    text_density_values: tuple[str, ...] = Field(min_length=1)
    hard_failures: tuple[str, ...] = Field(min_length=1)
    rules_sha256: str = Field(min_length=64, max_length=64)


class DesignSetPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    narrative_stages: list[str] = Field(min_length=1)
    visual_rhythm: list[str] = Field(min_length=1)
    product_presence_plan: list[str] = Field(min_length=1)
    layout_families: list[str] = Field(min_length=1)


class DesignImagePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sequence: int = Field(ge=1)
    page_role: str = Field(min_length=1)
    narrative_stage: str = Field(min_length=1)
    information_question: str = Field(min_length=1, max_length=300)
    product_presence: str = Field(min_length=1)
    subject_scale: str = Field(min_length=1)
    camera: str = Field(min_length=1)
    layout_family: str = Field(min_length=1)
    focal_point: str = Field(min_length=1)
    previous_module_contrast: str = Field(min_length=1, max_length=300)
    evidence: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


def load_design_knowledge(version: str = "v1") -> DesignKnowledgePack:
    if version != "v1":
        raise ValueError(f"unsupported design knowledge version: {version}")
    raw = json.loads(_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return DesignKnowledgePack(
        **raw,
        rules_sha256=sha256(canonical.encode("utf-8")).hexdigest(),
    )


def design_knowledge_context(pack: DesignKnowledgePack) -> dict[str, Any]:
    return {
        "version": pack.version,
        "rulesSha256": pack.rules_sha256,
        "principles": list(pack.principles),
        "narrativeStages": list(pack.narrative_stages),
        "layoutFamilies": list(pack.layout_families),
        "productPresenceValues": list(pack.product_presence_values),
        "subjectScaleValues": list(pack.subject_scale_values),
        "textDensityValues": list(pack.text_density_values),
        "hardFailures": list(pack.hard_failures),
    }
