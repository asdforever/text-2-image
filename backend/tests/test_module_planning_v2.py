from hashlib import sha256
import json

import httpx
import pytest

from backend.app.application.hero_generation_ports import PromptCompileRequest
from backend.app.application.suite_planning_service import SuitePlanCompilerRequest
from backend.app.application.module_planning_v2 import (
    SYSTEM_PROMPT_BASE,
    ModulePlanningV2Result,
    compose_v2_from_snapshot,
    freeze_v2_module_planning,
    render_v2_from_snapshot,
    render_v2_module_prompt,
    resolve_style_seed,
)
from backend.app.application.planning_skills import load_planning_skill
from backend.app.core.errors import AppError
from backend.app.generation_config_catalog import DEFAULT_STYLE_CATEGORIES
from backend.app.providers.openai_compatible import (
    OpenAICompatiblePromptCompiler,
    OpenAICompatibleSuitePlannerCompiler,
)


def _result_payload() -> dict:
    """模块规划器现在直接产出生图提示词，其余字段仅供界面展示。"""
    return {
        "imagePrompt": (
            "黑色耳机完整主体，略高于平视的三分之四视角，主体居中，右侧留出标题安全区。"
            "整体为冷灰与深蓝的克制色调，柔和侧光，干净浅灰背景。"
            "只允许出现「沉浸聆听」。无水印、无额外道具。"
        ),
        "copySummary": "突出黑色耳机的结构与核心卖点",
        "visualDirection": "主体居中偏左，右侧留白，冷灰基调的克制棚拍。",
        "exactCopy": ["沉浸聆听"],
        "visibleFacts": ["商品为黑色", "可见头梁和左右耳罩"],
        "unconfirmedItems": ["不确认灵敏度参数"],
    }


def test_professional_planning_requires_behavioral_product_appearance_decision() -> None:
    for mode in ("hero", "suite"):
        skill = load_planning_skill(mode)
        assert "产品行为" in skill.content
        assert "互动对象" in skill.content
        assert "compositionBrief" in skill.content
        assert "productPresence=context" in skill.content

    assert "产品行为" in SYSTEM_PROMPT_BASE
    assert "具体动作" in SYSTEM_PROMPT_BASE
    assert "compositionAdvice" in SYSTEM_PROMPT_BASE
    assert "模块级产品出场契约" in SYSTEM_PROMPT_BASE
    assert "suite-craft" in SYSTEM_PROMPT_BASE
    assert "hero-benefit" in SYSTEM_PROMPT_BASE


def test_v2_contract_requires_image_prompt_and_rejects_legacy_fields() -> None:
    # 旧版字段不再被接受
    with pytest.raises(ValueError):
        ModulePlanningV2Result.model_validate({"taskPrompt": "旧版模型直接生成的提示词"})

    with pytest.raises(ValueError):
        ModulePlanningV2Result.model_validate(
            {
                "imagePrompt": "画面描述",
                "styleRefinement": {"palette": ["冷灰"]},
            }
        )

    # imagePrompt 为空或只有空白必须被拒绝
    payload = _result_payload()
    payload["imagePrompt"] = "   "
    with pytest.raises(ValueError):
        ModulePlanningV2Result.model_validate(payload)

    # 未声明的字段同样被拒绝
    payload = _result_payload()
    payload["taskPrompt"] = "不得接受的额外字段"
    with pytest.raises(ValueError):
        ModulePlanningV2Result.model_validate(payload)


def test_v2_renderer_returns_image_prompt_verbatim() -> None:
    result = ModulePlanningV2Result.model_validate(_result_payload())

    prompt = render_v2_module_prompt(result)

    # 渲染器不再拼接字段，直接返回模型写出的画面描述
    assert prompt == result.imagePrompt.strip()
    assert "模块：" not in prompt
    assert "信息层级" not in prompt
    assert "构图：" not in prompt
    # 确定性：同一结果重复渲染完全一致
    assert prompt == render_v2_module_prompt(result)


def test_style_seed_freezes_builtin_and_safe_config_description_fallback() -> None:
    builtin = resolve_style_seed(
        {"id": "precision", "label": "冷调精密", "description": "任意配置描述"}
    )
    custom = resolve_style_seed(
        {"id": "custom-clean", "label": "自定义清爽", "description": "清透背景与自然柔光"}
    )

    assert builtin.seed_id == "builtin:precision"
    assert builtin.version == "style-seed-v2"
    assert builtin.sha256 == sha256(builtin.text.encode("utf-8")).hexdigest()
    assert custom.seed_id == "config:custom-clean"
    assert custom.text == "清透背景与自然柔光"
    assert custom.version == "config-style-description-v1"

    with pytest.raises(AppError) as raised:
        resolve_style_seed({"id": "custom-empty", "label": "空", "description": "  "})
    assert raised.value.code == "STYLE_SEED_INVALID"


def test_every_builtin_style_has_a_fixed_seed() -> None:
    styles = [style for category in DEFAULT_STYLE_CATEGORIES for style in category["styles"]]
    seeds = [resolve_style_seed(style) for style in styles]

    assert len(seeds) == 21
    assert all(seed.seed_id == f"builtin:{seed.style_id}" for seed in seeds)
    assert all(seed.text and len(seed.sha256) == 64 for seed in seeds)


def test_frozen_rendered_prompt_survives_renderer_upgrade_and_detects_tampering() -> None:
    result = ModulePlanningV2Result.model_validate(_result_payload())
    rendered = render_v2_module_prompt(result)
    planning = freeze_v2_module_planning(result, rendered)
    planning["rendererVersion"] = "future-renderer-v99"
    snapshot = {"modulePlanning": planning}

    assert render_v2_from_snapshot(snapshot) == rendered
    assert planning["composerVersion"]

    snapshot["modulePlanning"]["renderedPrompt"] += " tampered"
    with pytest.raises(AppError) as raised:
        render_v2_from_snapshot(snapshot)
    assert raised.value.code == "MODULE_PLANNING_SNAPSHOT_INVALID"

    # 结果哈希被篡改时同样拒绝
    snapshot["modulePlanning"]["renderedPrompt"] = rendered
    snapshot["modulePlanning"]["result"]["imagePrompt"] = "被篡改的画面描述"
    with pytest.raises(AppError) as raised:
        render_v2_from_snapshot(snapshot)
    assert raised.value.code == "MODULE_PLANNING_SNAPSHOT_INVALID"


def test_compose_from_snapshot_returns_image_prompt_without_appending_constraints() -> None:
    result = ModulePlanningV2Result.model_validate(_result_payload())
    rendered = render_v2_module_prompt(result)
    snapshot = {
        "selection": {
            "aspectRatio": "1:1",
            "resolution": "标准 1K",
            "outputLanguage": "中文",
        },
        "constraints": {
            "authenticity": {"content": "保持商品真实"},
            "market": {"content": "遵守平台规则"},
        },
        "modulePlanning": freeze_v2_module_planning(result, rendered),
    }

    final_prompt = compose_v2_from_snapshot(snapshot)

    # 约束与输出规格已作为输入交给模块规划器，不再在末尾追加
    assert final_prompt == rendered
    assert "商品真实性与来源约束" not in final_prompt
    assert "输出规格：" not in final_prompt


@pytest.mark.asyncio
async def test_prompt_provider_requires_strict_v2_result_when_request_is_v2() -> None:
    responses = [_result_payload(), {
        "taskPrompt": "旧版模型直接生成的提示词",
        "visibleFacts": [],
        "unconfirmedItems": [],
    }]
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        content = json.dumps(responses.pop(0), ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    compiler = OpenAICompatiblePromptCompiler(
        base_url="https://model.test/v1",
        api_key="secret",
        model="context-model",
        timeout_ms=100,
        transport=httpx.MockTransport(handler),
    )
    request = PromptCompileRequest(
        system_prompt="strict v2",
        user_prompt="module context",
        image_bytes=b"image",
        image_mime_type="image/png",
        planner_version="v2",
    )

    result = await compiler.compile(request)
    assert isinstance(result, ModulePlanningV2Result)
    assert sent[0]["response_format"] == {"type": "json_object"}

    with pytest.raises(AppError) as raised:
        await compiler.compile(request)
    assert raised.value.code == "PROMPT_COMPILER_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_suite_provider_requires_strict_v2_result_when_request_is_v2() -> None:
    responses = [_result_payload(), {
        "copySummary": "旧摘要",
        "visualDirection": "旧画面",
        "taskPrompt": "旧版最终提示词",
        "visibleFacts": [],
        "unconfirmedItems": [],
    }]

    def handler(_request: httpx.Request) -> httpx.Response:
        content = json.dumps(responses.pop(0), ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    compiler = OpenAICompatibleSuitePlannerCompiler(
        base_url="https://model.test/v1",
        api_key="secret",
        model="context-model",
        timeout_ms=100,
        transport=httpx.MockTransport(handler),
    )
    request = SuitePlanCompilerRequest(
        module_id="suite-hero",
        module={"id": "suite-hero"},
        module_parameters=[],
        image_inputs=[b"image"],
        image_mime_types=["image/png"],
        system_prompt="strict v2",
        user_prompt="module context",
        planner_version="v2",
    )

    assert isinstance(await compiler.compile(request), ModulePlanningV2Result)
    with pytest.raises(AppError) as raised:
        await compiler.compile(request)
    assert raised.value.code == "PLANNING_COMPILER_INVALID_RESPONSE"
