"""Exercise the planning agent through its real model HTTP boundary."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.application.module_planning_service import ModuleMasterRequest
from backend.app.core.errors import AppError
from backend.app.providers.openai_compatible import OpenAICompatibleModulePlanner
from backend.tests.test_module_planning import fixture, output


def response(value):
    return httpx.Response(200, json={
        "id": "chatcmpl-planning", "object": "chat.completion", "created": 1,
        "model": "vision-model", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(value)}}],
    })


def planner(handler, base_url="https://vision.example.test"):
    return OpenAICompatibleModulePlanner(
        base_url=base_url, api_key="test-key", model="vision-model",
        timeout_ms=1000, transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata_type", ["text", "object", "suite"])
async def test_regular_agent_accepts_root_type_metadata_without_changing_content(metadata_type):
    f = await fixture("suite")
    request = f.input.model_copy(update={
        "creationMode": "regular",
        "selectedModules": [{"taskId": "a", "moduleId": "suite-hero"}],
    })
    raw = {"type": metadata_type, "summary": "商品介绍", "warnings": [], "modules": [{
        "taskId": "a", "moduleId": "suite-hero", "taskTitle": "商品识别",
        "reason": "展示材质", "suggestedCopy": "纯棉", "moduleParameters": [{"key": "材质", "value": "纯棉"}],
    }]}

    async def handler(_request):
        return response(raw)

    f.master_service.planner = planner(handler)
    result = await f.master_service.plan(f.project_id, request, "root-type-metadata")
    assert result["status"] == "completed"
    assert result["summary"] == "商品介绍"
    assert result["modules"][0]["taskId"] == "a"
    assert result["modules"][0]["moduleParameters"] == [{"key": "材质", "value": "纯棉"}]
    assert "type" not in result


@pytest.mark.asyncio
async def test_regular_agent_still_rejects_unknown_business_fields_with_type_metadata():
    f = await fixture("suite")
    request = f.input.model_copy(update={"creationMode": "regular"})
    raw = {"type": "object", "unknownBusinessField": True, "summary": "商品介绍", "warnings": [], "modules": [{
        "taskId": "a", "moduleId": "suite-hero", "taskTitle": "商品识别",
        "reason": "展示材质", "suggestedCopy": "纯棉", "moduleParameters": [],
    }]}

    async def handler(_request):
        return response(raw)

    f.master_service.planner = planner(handler)
    with pytest.raises(AppError) as error:
        await f.master_service.plan(f.project_id, request, "unknown-business-field")
    assert error.value.code == "MODULE_PLANNER_INVALID_RESPONSE"
    saved = await f.master_service.latest(f.project_id, "suite")
    assert saved["snapshot"]["validationErrors"] == [
        {"field": "unknownBusinessField", "type": "extra_forbidden"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hero", "suite"])
@pytest.mark.parametrize("creation_mode", ["regular", "professional"])
async def test_agent_plans_with_images_and_preserves_replay(mode, creation_mode):
    f = await fixture(mode)
    f.input = f.input.model_copy(update={"creationMode": creation_mode})
    raw = output(mode)
    if creation_mode == "regular":
        raw = {"summary": "展示商品", "warnings": [], "modules": [{
            "taskId": "first", "moduleId": raw["modules"][0]["moduleId"],
            "taskTitle": "认识商品", "reason": "建立第一印象",
            "suggestedCopy": "看清外观", "moduleParameters": [],
        }]}
    requests = []

    async def handler(request):
        requests.append(request)
        return response(raw)

    f.master_service.planner = planner(handler)
    result = await f.master_service.plan(f.project_id, f.input, "agent-replay")
    replay = await f.master_service.plan(f.project_id, f.input, "agent-replay")

    assert result["status"] == "completed"
    assert replay["id"] == result["id"]
    assert result["modules"][0]["taskTitle"] == "认识商品"
    assert result["snapshot"]["planningEngine"] == {
        "framework": "langchain", "factory": "create_agent",
        "tools": [], "sdkMaxRetries": 0,
    }
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://vision.example.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-key"
    sent = json.loads(request.content)
    assert sent["model"] == "vision-model"
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["messages"][0] == {"role": "system", "content": result["snapshot"]["systemPrompt"]}
    content = sent["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": result["snapshot"]["userPrompt"]}
    assert len(content) == 3
    assert all(item["image_url"]["url"].startswith("data:image/") for item in content[1:])
    assert "tools" not in sent


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [
    (401, "UNAUTHORIZED"), (402, "QUOTA_EXHAUSTED"),
    (429, "QUOTA_EXHAUSTED"), (400, "INVALID_REQUEST"), (500, "FAILED"),
])
async def test_agent_does_not_retry_or_expose_upstream_errors(status, code):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "secret upstream body"}})

    with pytest.raises(AppError) as exc:
        await planner(handler).plan_modules(ModuleMasterRequest("JSON", "商品", [b"png"], ["image/png"]))
    assert exc.value.code == "MODULE_PLANNER_" + code
    assert "secret" not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_agent_timeout_is_normalized_without_sdk_retry():
    calls = []

    async def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret", request=request)

    with pytest.raises(AppError) as exc:
        await planner(handler).plan_modules(ModuleMasterRequest("JSON", "商品", [b"png"], ["image/png"]))
    assert exc.value.code == "MODULE_PLANNER_TIMEOUT"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_agent_connections_remain_task_local():
    requests = []

    async def handler(request):
        requests.append(request)
        return response({"summary": "完成"})

    original = planner(handler)
    bound = original.with_connection(SimpleNamespace(
        base_url="https://other.example.test/api/v1", api_key="other-key", model_name="other-model",
    ))
    request = ModuleMasterRequest("JSON", "商品", [b"png"], ["image/png"])
    await asyncio.gather(original.plan_modules(request), bound.plan_modules(request))
    sent = {r.headers["Authorization"]: (str(r.url), json.loads(r.content)["model"]) for r in requests}
    assert sent == {
        "Bearer test-key": ("https://vision.example.test/v1/chat/completions", "vision-model"),
        "Bearer other-key": ("https://other.example.test/api/v1/chat/completions", "other-model"),
    }


@pytest.mark.asyncio
async def test_agent_correction_still_uses_only_two_business_attempts():
    f = await fixture()
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        raw = output()
        if len(requests) == 1:
            raw["modules"][0]["moduleId"] = "unknown-module"
        return response(raw)

    f.master_service.planner = planner(handler)
    result = await f.master_service.plan(f.project_id, f.input, "agent-correction")
    assert result["status"] == "completed"
    assert len(requests) == 2
    correction = json.loads(requests[1]["messages"][1]["content"][0]["text"])["correction"]
    assert correction["previousOutput"]["modules"][0]["moduleId"] == "unknown-module"
    attempts = result["snapshot"]["modelAttempts"]
    assert len(attempts) == 2
    assert attempts[0]["validationErrors"]


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"choices": []}, {"choices": None}, {},
    {"choices": [{"message": {"role": "assistant", "content": "not JSON"}}]},
    {"choices": [{"message": {"role": "assistant", "content": "[]"}}]},
])
async def test_agent_rejects_invalid_response(body):
    async def handler(request):
        return httpx.Response(200, json=body)

    with pytest.raises(AppError) as exc:
        await planner(handler).plan_modules(ModuleMasterRequest("JSON", "商品", [b"png"], ["image/png"]))
    assert exc.value.code == "MODULE_PLANNER_INVALID_RESPONSE"
