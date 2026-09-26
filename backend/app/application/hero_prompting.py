from dataclasses import dataclass
from copy import deepcopy
from hashlib import sha256
from typing import Any
from uuid import UUID

from ..core.errors import AppError
from .prompt_usage import require_image_prompt


PRODUCT_AUTHENTICITY_CONSTRAINT = (
    "必须保持源图中商品的身份、结构、颜色、材质和可见细节真实一致；"
    "不得凭空增加配件、功能、规格、认证、功效或无法确认的商品事实。"
)


@dataclass(frozen=True)
class ConstraintCard:
    content: str
    source: str
    content_sha256: str
    prompt_template_id: UUID | None = None
    prompt_version_id: UUID | None = None
    prompt_version_sha256: str | None = None

    def to_snapshot(self) -> dict[str, str | None]:
        return {
            "content": self.content,
            "source": self.source,
            "contentSha256": self.content_sha256,
            "promptTemplateId": (
                str(self.prompt_template_id) if self.prompt_template_id is not None else None
            ),
            "promptVersionId": (
                str(self.prompt_version_id) if self.prompt_version_id is not None else None
            ),
            "promptVersionSha256": self.prompt_version_sha256,
        }


@dataclass(frozen=True)
class ConstraintCards:
    authenticity: ConstraintCard
    market: ConstraintCard
    style: ConstraintCard

    def to_snapshot(self) -> dict[str, dict[str, str | None]]:
        return {
            "authenticity": self.authenticity.to_snapshot(),
            "market": self.market.to_snapshot(),
            "style": self.style.to_snapshot(),
        }


async def resolve_constraint_cards(
    published_config: dict[str, Any],
    *,
    market_id: str,
    style_id: str,
    prompt_repository: Any,
    style_seed: str | None = None,
) -> ConstraintCards:
    market = _find_by_id(published_config.get("markets"), market_id, "电商平台")
    _find_style(published_config.get("styleCategories"), style_id)
    market_card = await _resolve_bound_card(
        fallback=str(market.get("guidance", "")).strip(),
        fallback_source="market_guidance",
        binding=published_config.get("marketBindings", {}).get(market_id),
        prompt_repository=prompt_repository,
    )
    if style_seed is None:
        raise AppError("STYLE_SEED_INVALID", "风格种子不能为空", 500)
    style_card = _card(style_seed, "style_seed_v2")
    return ConstraintCards(
        authenticity=_card(PRODUCT_AUTHENTICITY_CONSTRAINT, "server_policy"),
        market=market_card,
        style=style_card,
    )


async def _resolve_bound_card(
    *,
    fallback: str,
    fallback_source: str,
    binding: Any,
    prompt_repository: Any,
) -> ConstraintCard:
    if binding is None:
        if not fallback:
            raise AppError("GENERATION_CONFIG_INVALID", "未绑定提示词且配置说明为空", 400)
        return _card(fallback, fallback_source)
    if not isinstance(binding, dict):
        raise AppError("GENERATION_CONFIG_PROMPT_BINDING_INVALID", "提示词绑定格式无效", 409)

    try:
        template_id = UUID(str(binding["promptTemplateId"]))
        version_id = UUID(str(binding["promptVersionId"]))
    except (KeyError, TypeError, ValueError):
        raise AppError(
            "GENERATION_CONFIG_PROMPT_BINDING_INVALID",
            "提示词绑定无效，请重新确认绑定",
            409,
        ) from None
    version = await prompt_repository.get_version(version_id)
    if version is None or version.template_id != template_id:
        raise AppError(
            "GENERATION_CONFIG_PROMPT_VERSION_NOT_FOUND",
            "绑定的提示词版本不可用，请重新确认绑定",
            409,
        )
    require_image_prompt(version)
    runtime_template = version.user_prompt_template.strip()
    content = runtime_template or version.body
    source = "prompt_version_user_template" if runtime_template else "prompt_version_body"
    if not content.strip():
        raise AppError("GENERATION_CONFIG_PROMPT_EMPTY", "绑定的提示词正文为空，请完善提示词后重新绑定", 409)
    expected_hash = binding.get("contentSha256")
    if expected_hash and expected_hash != version.content_sha256:
        raise AppError("GENERATION_CONFIG_PROMPT_CHANGED", "绑定提示词版本内容已改变，请重新确认绑定", 409)
    return _card(
        content,
        source,
        prompt_template_id=template_id,
        prompt_version_id=version_id,
        prompt_version_sha256=version.content_sha256,
    )


async def restore_bound_constraints(constraints: dict, prompt_repository: Any) -> dict:
    """仅补全旧缺陷遗漏的绑定原文；不改历史快照，也不追随目录的新绑定。"""
    restored = deepcopy(constraints)
    for key, source in (("market", "market_guidance"), ("style", "style_description")):
        card = constraints.get(key, {})
        if card.get("source") != source or not card.get("promptVersionId"):
            continue
        # 快照的 contentSha256 校验短约束内容；绑定版本使用独立的版本哈希。
        binding = {
            "promptTemplateId": card.get("promptTemplateId"),
            "promptVersionId": card["promptVersionId"],
            "contentSha256": card.get("promptVersionSha256"),
        }
        resolved = await _resolve_bound_card(fallback=card.get("content", ""), fallback_source=source, binding=binding, prompt_repository=prompt_repository)
        restored[key] = resolved.to_snapshot()
    return restored


MODULE_BINDING_KEYS = {"hero": "heroBindings", "suite": "suiteBindings"}


async def resolve_module_prompt(
    published_config: dict[str, Any],
    *,
    mode: str,
    module_id: str,
    prompt_repository: Any,
) -> str:
    """解析模块绑定的规划提示词正文。

    未绑定时返回空串，由调用方回退到通用规范；绑定了但版本不可用则报错，
    避免静默使用过期内容。
    """
    binding_key = MODULE_BINDING_KEYS.get(mode)
    if binding_key is None:
        raise AppError("GENERATION_CONFIG_SELECTION_INVALID", f"未知模块类型：{mode}", 400)
    binding = (published_config.get(binding_key) or {}).get(module_id)
    if not binding:
        return ""
    if not isinstance(binding, dict):
        raise AppError("GENERATION_CONFIG_PROMPT_BINDING_INVALID", "模块提示词绑定格式无效", 409)
    try:
        template_id = UUID(str(binding["promptTemplateId"]))
        version_id = UUID(str(binding["promptVersionId"]))
    except (KeyError, TypeError, ValueError):
        raise AppError(
            "GENERATION_CONFIG_PROMPT_BINDING_INVALID",
            "模块提示词绑定无效，请重新确认绑定",
            409,
        ) from None
    version = await prompt_repository.get_version(version_id)
    if version is None or version.template_id != template_id:
        raise AppError(
            "GENERATION_CONFIG_PROMPT_VERSION_NOT_FOUND",
            "绑定的模块提示词版本不可用，请重新确认绑定",
            409,
        )
    expected_hash = binding.get("contentSha256")
    if expected_hash and expected_hash != version.content_sha256:
        raise AppError(
            "GENERATION_CONFIG_PROMPT_CHANGED",
            "绑定的模块提示词内容已改变，请重新确认绑定",
            409,
        )
    return (version.body or "").strip()


def _find_by_id(items: Any, item_id: str, label: str) -> dict[str, Any]:
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("id") == item_id:
                return item
    raise AppError("GENERATION_CONFIG_SELECTION_INVALID", f"{label}选择无效", 400)


def _find_style(categories: Any, style_id: str) -> dict[str, Any]:
    if isinstance(categories, list):
        for category in categories:
            if not isinstance(category, dict):
                continue
            try:
                return _find_by_id(category.get("styles"), style_id, "图片风格")
            except AppError:
                continue
    raise AppError("GENERATION_CONFIG_SELECTION_INVALID", "图片风格选择无效", 400)


def _card(
    content: str,
    source: str,
    *,
    prompt_template_id: UUID | None = None,
    prompt_version_id: UUID | None = None,
    prompt_version_sha256: str | None = None,
) -> ConstraintCard:
    return ConstraintCard(
        content=content,
        source=source,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
        prompt_template_id=prompt_template_id,
        prompt_version_id=prompt_version_id,
        prompt_version_sha256=prompt_version_sha256,
    )
