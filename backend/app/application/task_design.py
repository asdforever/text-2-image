"""User design choices, separate from product facts and generated advice."""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskDesignInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    taskTitle: str | None = Field(default=None, max_length=80)
    informationQuestion: str | None = Field(default=None, max_length=300)
    visualMechanism: str | None = Field(default=None, max_length=500)
    productPresence: Literal["auto", "full", "partial", "detail", "context", "none"] | None = None


def resolve_task_design(outline: dict | None, design: dict | None) -> tuple[dict | None, dict]:
    explicit = TaskDesignInput.model_validate(design or {}).model_dump(exclude_none=True)
    effective = deepcopy(outline) if outline is not None else None
    if explicit:
        effective = {**(effective or {}), **explicit}
    return effective, explicit
