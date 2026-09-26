"""Load application-owned planning instructions; never accept user-provided paths."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from ..core.errors import AppError


@dataclass(frozen=True)
class PlanningSkill:
    name: str
    content: str

    def to_snapshot(self) -> dict[str, str]:
        return {
            "name": self.name,
            "source": "builtin_skill",
            "contentSha256": sha256(self.content.encode("utf-8")).hexdigest(),
        }


def load_planning_skill(mode: Literal["hero", "suite"]) -> PlanningSkill:
    name = {"hero": "hero-planning-master", "suite": "suite-planning-master"}[mode]
    path = Path(__file__).resolve().parents[1] / "skills" / name / "SKILL.md"
    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            raise ValueError("empty skill")
    except (OSError, UnicodeError, ValueError):
        raise AppError("MODULE_PLANNER_SKILL_UNAVAILABLE", "自动规划服务配置不可用，请联系管理员", 503) from None
    return PlanningSkill(name, content)
