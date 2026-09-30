"""Keep planning instructions out of direct-image execution paths."""

from ..core.errors import AppError


def require_image_prompt(version) -> None:
    role = (version.applicability or {}).get("runtimeRole")
    if role in {"style-seed", "style-planner", "planner", "hero-module-planner", "suite-module-planner"}:
        raise AppError(
            "PROMPT_REQUIRES_PLANNING",
            "这是风格或规划模板，请在主图或详情页工作台使用；直接生图请使用完整提示词。",
            400,
        )
