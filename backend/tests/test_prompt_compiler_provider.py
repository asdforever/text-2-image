import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.application.hero_generation_ports import PromptCompileRequest
from backend.app.core.errors import AppError
from backend.app.providers.openai_compatible import (
    OpenAICompatibleModulePlanner,
    OpenAICompatiblePromptCompiler,
    OpenAICompatibleSuitePlannerCompiler,
)
from backend.app.application.module_planning_service import ModuleMasterRequest


@pytest.mark.asyncio
async def test_suite_planner_compiler_sends_all_images_and_parses_module_plan() -> None:
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        from backend.tests.test_module_planning_v2 import _result_payload
        captured["payload"] = json.loads((await request.aread()).decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(_result_payload(), ensure_ascii=False)}}]})

    compiler = OpenAICompatibleSuitePlannerCompiler(
        base_url="https://vision.example.test/v1", api_key="secret",
        model="vision-model", timeout_ms=1000, transport=httpx.MockTransport(handler),
    )
    result = await compiler.compile(SimpleNamespace(
        image_inputs=[b"first", b"second"],
        image_mime_types=["image/png", "image/jpeg"],
        system_prompt="系统", user_prompt="用户",
    ))

    content = captured["payload"]["messages"][1]["content"]
    assert [item["type"] for item in content] == ["text", "image_url", "image_url"]
    assert result.imagePrompt
    assert result.copySummary


@pytest.mark.asyncio
async def test_module_planner_unwraps_text_content_envelope() -> None:
    master = {
        "summary": "先建立识别，再解释细节。",
        "modules": [
            {
                "moduleId": "suite-hero",
                "resultCount": 1,
                "moduleParameters": [],
                "compositionBrief": "完整展示商品。",
                "reason": "建立识别。",
            }
        ],
    }

    async def handler(_request: httpx.Request) -> httpx.Response:
        wrapped = {"type": "text", "content": json.dumps(master, ensure_ascii=False)}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(wrapped, ensure_ascii=False)}}]})

    planner = OpenAICompatibleModulePlanner(
        base_url="https://vision.example.test/v1", api_key="secret",
        model="vision-model", timeout_ms=1000, transport=httpx.MockTransport(handler),
    )
    result = await planner.plan_modules(ModuleMasterRequest("系统", "用户", [b"image"], ["image/png"]))

    assert result["modules"][0]["moduleId"] == "suite-hero"


@pytest.mark.asyncio
async def test_prompt_compiler_sends_image_and_returns_structured_result() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        from backend.tests.test_module_planning_v2 import _result_payload
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads((await request.aread()).decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(_result_payload(), ensure_ascii=False)}}]})

    compiler = OpenAICompatiblePromptCompiler(
        base_url="https://vision.example.test/v1",
        api_key="compiler-secret",
        model="vision-model",
        timeout_ms=123000,
        transport=httpx.MockTransport(handler),
    )
    result = await compiler.compile(
        PromptCompileRequest(
            system_prompt="只根据可见事实规划主图任务提示词。",
            user_prompt="模块：纯色背景；补充参数：主体居中。",
            image_bytes=b"fake-png-bytes",
            image_mime_type="image/png",
        )
    )

    assert result.imagePrompt
    assert result.copySummary
    assert captured["url"] == "https://vision.example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer compiler-secret"
    assert captured["payload"] == {
        "model": "vision-model",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "只根据可见事实规划主图任务提示词。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "模块：纯色背景；补充参数：主体居中。"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(b"fake-png-bytes").decode("ascii")
                        },
                    },
                ],
            },
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        json.dumps({"taskPrompt": "", "visibleFacts": [], "unconfirmedItems": []}),
        json.dumps({"taskPrompt": "ok", "visibleFacts": "黑色", "unconfirmedItems": []}),
    ],
)
async def test_prompt_compiler_rejects_malformed_structured_output(content: str) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        )

    compiler = OpenAICompatiblePromptCompiler(
        base_url="https://vision.example.test/v1",
        api_key="secret",
        model="vision-model",
        timeout_ms=1000,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AppError) as raised:
        await compiler.compile(_compile_request())

    assert raised.value.code == "PROMPT_COMPILER_INVALID_RESPONSE"
    assert raised.value.status_code == 502


@pytest.mark.asyncio
async def test_prompt_compiler_normalizes_timeout_without_exposing_secret() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("compiler-secret leaked upstream", request=request)

    compiler = OpenAICompatiblePromptCompiler(
        base_url="https://compiler-secret.example.test/v1",
        api_key="compiler-secret",
        model="vision-model",
        timeout_ms=1000,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AppError) as raised:
        await compiler.compile(_compile_request())

    assert raised.value.code == "PROMPT_COMPILER_TIMEOUT"
    assert raised.value.message == "prompt compiler timed out"
    assert "compiler-secret" not in str(raised.value)
    assert "compiler-secret" not in repr(raised.value)


@pytest.mark.asyncio
async def test_prompt_compiler_normalizes_http_failure_without_upstream_body() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "invalid key compiler-secret", "token": "compiler-secret"}},
        )

    compiler = OpenAICompatiblePromptCompiler(
        base_url="https://vision.example.test/v1",
        api_key="compiler-secret",
        model="vision-model",
        timeout_ms=1000,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AppError) as raised:
        await compiler.compile(_compile_request())

    assert raised.value.code == "PROMPT_COMPILER_UNAUTHORIZED"
    assert "API Key" in raised.value.message
    assert "compiler-secret" not in str(raised.value)
    assert "compiler-secret" not in repr(raised.value)


@pytest.mark.asyncio
async def test_unconfigured_prompt_compiler_fails_only_when_compile_is_requested() -> None:
    compiler = OpenAICompatiblePromptCompiler(
        base_url=None,
        api_key=None,
        model=None,
        timeout_ms=1000,
    )

    with pytest.raises(AppError) as raised:
        await compiler.compile(_compile_request())

    assert raised.value.code == "PROMPT_COMPILER_UNAVAILABLE"
    assert raised.value.status_code == 503


def _compile_request() -> PromptCompileRequest:
    return PromptCompileRequest(
        system_prompt="只根据可见事实规划主图任务提示词。",
        user_prompt="模块：纯色背景。",
        image_bytes=b"fake-png-bytes",
        image_mime_type="image/png",
    )
