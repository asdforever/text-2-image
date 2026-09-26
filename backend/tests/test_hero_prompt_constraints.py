from uuid import UUID

import pytest

from backend.app.application.hero_prompting import (
    PRODUCT_AUTHENTICITY_CONSTRAINT,
    resolve_constraint_cards,
)
from backend.app.prompt_repository import MemoryPromptRepository


@pytest.mark.asyncio
async def test_market_template_resolves_alongside_fixed_style_seed() -> None:
    prompts = MemoryPromptRepository()
    template, version = await prompts.create_template_with_version(
        code="market-taobao", name="淘宝约束", kind="generation", kind_name="图片生成",
        execution_target="image", body="内部操作规范", user_prompt_template="白底，无水印。",
    )
    config = {"markets": [{"id": "taobao", "guidance": "default"}], "styleCategories": [{"styles": [{"id": "precision", "description": "default"}]}], "marketBindings": {"taobao": _binding(template.id, version.id, version.content_sha256)}}
    cards = await resolve_constraint_cards(
        config, market_id="taobao", style_id="precision", prompt_repository=prompts,
        style_seed="冷灰基调与清晰结构",
    )
    assert cards.market.content == "白底，无水印。"
    assert cards.style.content == "冷灰基调与清晰结构"
    assert cards.style.source == "style_seed_v2"
    assert cards.authenticity.content == PRODUCT_AUTHENTICITY_CONSTRAINT


def _binding(template_id: UUID, version_id: UUID, content_sha256: str) -> dict[str, str]:
    return {"promptTemplateId": str(template_id), "promptVersionId": str(version_id), "contentSha256": content_sha256}
