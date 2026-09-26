from copy import deepcopy
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from backend.app.core.errors import AppError
from backend.app.application.module_planning_service import ModulePlanningService, ModulePlanInput
from backend.app.application.image_style_library import STYLE_LIBRARY_PLANNING_RULES
from backend.app.module_planning_repository import MemoryModulePlanningRepository
from backend.tests.test_suite_planning_service import _fixture, SuitePlanCompilationInput, SuitePlanModuleInput


def output(mode="suite"):
    return {"summary": "先认识商品，再了解细节", "modules": [
        {"moduleId": f"{mode}-hero" if mode == "suite" else "hero-kv", "resultCount": 1,
         "moduleParameters": [{"key": "首要信息", "value": "商品外观"}],
         "compositionBrief": "产品居中，下方留标题区域", "reason": "建立第一印象",
         "styleTemplateId": "product-commerce-visual", "bigIdea": "商品与用途呼应",
         "visualMechanism": "商品与使用场景形成关系"},
        {"moduleId": f"{mode}-detail", "resultCount": 1,
         "moduleParameters": [{"key": "细节主体", "value": "按键"}],
         "compositionBrief": "左右分栏展示按键特写和位置示意", "reason": "展示可见细节",
         "styleTemplateId": "infographic-engine", "bigIdea": "看清操作细节",
         "visualMechanism": "可见细节与短标签相连"},
    ], "warnings": ["续航未提供"]}


class Planner:
    def __init__(self, result=None):
        self.result = result or output()
        self.calls = []

    async def plan_modules(self, request):
        self.calls.append(request)
        return deepcopy(self.result)


async def fixture(mode="suite"):
    f = await _fixture()
    f.master = Planner(output(mode))
    f.master_repo = MemoryModulePlanningRepository()
    f.master_service = ModulePlanningService(
        f.master_repo, f.projects, f.storage, f.config, f.prompts,
        f.service.identity_provider, f.master,
    )
    f.input = ModulePlanInput(mode=mode, sourceAssetIds=f.source_asset_ids,
        marketId="taobao", aspectRatio="3:4", outputLanguage="中文", brief="展示外观和按键")
    return f


@pytest.mark.asyncio
async def test_master_binds_prompt_model_with_resolver_contract():
    f = await fixture()

    class Resolver:
        async def bind(self, published_config, compiler):
            return SimpleNamespace(compiler=compiler, snapshot={"modelName": "test-model"})

    f.master_service.prompt_models = Resolver()

    result = await f.master_service.plan(f.project_id, f.input, "prompt-model-bind")

    assert result["status"] == "completed"
    assert result["snapshot"]["promptModelConnection"] == {"modelName": "test-model"}
    assert len(f.master.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hero", "suite"])
async def test_master_selects_modules_persists_output_and_replays_without_model(mode):
    f = await fixture(mode)
    result = await f.master_service.plan(f.project_id, f.input, "master-1")
    assert result["status"] == "completed"
    assert len(result["modules"]) == 2
    assert result["modules"][0]["moduleParameters"][-1] == {
        "key": "建议构图简案", "value": "产品居中，下方留标题区域"}
    assert (await f.master_service.latest(f.project_id, mode))["id"] == result["id"]
    assert (await f.master_service.plan(f.project_id, f.input, "master-1"))["id"] == result["id"]
    assert len(f.master.calls) == 1
    assert len(f.master.calls[0].image_inputs) == 2
    with pytest.raises(AppError):
        await f.master_service.plan(f.project_id, f.input.model_copy(update={"brief": "不同"}), "master-1")
    with pytest.raises(AppError):
        await f.master_service.get(uuid4(), UUID(result["id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda x: x["modules"][0].update(moduleId="invented"),
    lambda x: x["modules"][1].update(moduleId="suite-hero"),
    lambda x: x["modules"][0].update(resultCount=True),
    lambda x: x["modules"][0].update(resultCount=2),
    lambda x: x["modules"][0].update(resultCount=5),
    lambda x: x["modules"][0].update(compositionBrief=""),
    lambda x: x.update(modules=[]),
])
async def test_invalid_master_output_is_failed_and_never_applied(mutation):
    f = await fixture()
    mutation(f.master.result)
    with pytest.raises(AppError) as exc:
        await f.master_service.plan(f.project_id, f.input, "invalid")
    assert exc.value.code == "MODULE_PLANNER_INVALID_RESPONSE"
    failed = await f.master_service.latest(f.project_id, "suite")
    assert failed["status"] == "failed"
    assert failed["snapshot"]["generationConfig"]["contentSha256"]
    assert failed["snapshot"]["systemPrompt"]
    assert f.compiler.requests == []


@pytest.mark.asyncio
async def test_master_brief_flows_into_suite_compiler_and_frozen_snapshot():
    f = await fixture()
    f.master.result["modules"][0].update(styleTemplateId="product-commerce-visual",
        bigIdea="商品与用途呼应", visualMechanism="物体与场景形成使用关系")
    f.master.result["modules"][1].update(styleTemplateId="infographic-engine")
    result = await f.master_service.plan(f.project_id, f.input, "outline")
    f.service.module_planning = f.master_service
    req = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids, market_id="taobao",
        model_id="gpt-image-2-5", style_id="minimal", aspect_ratio="3:4", resolution="标准 1K",
        output_language="中文", module_plan_id=UUID(result["id"]),
        modules=[SuitePlanModuleInput(m["moduleId"], m["resultCount"], m["moduleParameters"])
                 for m in result["modules"]])
    plan = await f.service.compile_plan(f.project_id, req, "compile-outline")
    detail = await f.plans.get_plan_detail(plan.id, f.workspace_id, f.project_id)
    assert detail.plan.snapshot["planningMaster"]["id"] == result["id"]
    assert "产品居中，下方留标题区域" in f.compiler.requests[0].user_prompt
    assert "左右分栏展示按键特写" in f.compiler.requests[1].user_prompt
    assert "展示外观和按键" in f.compiler.requests[0].user_prompt
    library = json.loads(f.master.calls[0].user_prompt)["styleLibrary"]
    assert library == result["snapshot"]["styleLibrary"]
    assert len(library["templates"]) == 22
    for index, template_id in enumerate(["product-commerce-visual", "infographic-engine"]):
        context = json.loads(f.compiler.requests[index].user_prompt)
        assert [t["id"] for t in context["styleLibrary"]["templates"]] == [template_id]
        assert context["styleLibrary"]["templates"][0]["promptTemplate"]
        assert detail.modules[index].prompt_snapshot["styleLibrarySha256"] == context["styleLibrary"]["contentSha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [
    {"styleTemplateId": "invented-template"},
    {"styleTemplateId": "infographic-engine", "referenceCaseIds": [377]},
    {"styleTemplateId": "", "referenceCaseIds": [334]},
])
async def test_master_rejects_unknown_style_template_before_compile(selection):
    f = await fixture()
    f.master.result["modules"][0].update(selection)
    with pytest.raises(AppError) as exc:
        await f.master_service.plan(f.project_id, f.input, "unknown-template")
    assert exc.value.code == "MODULE_PLANNER_INVALID_RESPONSE"
    assert (await f.master_service.latest(f.project_id, "suite"))["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["styleTemplateId", "bigIdea", "visualMechanism"])
@pytest.mark.parametrize("value", [None, "", "   "])
async def test_fresh_master_requires_template_and_concrete_idea(field, value):
    f = await fixture()
    if value is None:
        f.master.result["modules"][0].pop(field)
    else:
        f.master.result["modules"][0][field] = value
    with pytest.raises(AppError) as exc:
        await f.master_service.plan(f.project_id, f.input, "missing-style-choice")
    assert exc.value.code == "MODULE_PLANNER_INVALID_RESPONSE"
    saved = await f.master_service.latest(f.project_id, "suite")
    assert saved["status"] == "failed"
    assert saved["modules"] == []
    assert len(f.master.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda value: value.update(summaryNote="extra explanation"),
    lambda value: value["modules"][0].pop("styleTemplateId"),
    lambda value: value["modules"][0].update(moduleId="unknown"),
])
async def test_invalid_model_output_is_corrected_once_before_saving(mutation):
    f = await fixture()
    invalid = output()
    mutation(invalid)
    responses = iter([invalid, output()])
    async def responding(request):
        f.master.calls.append(request)
        return next(responses)
    f.master.plan_modules = responding
    result = await f.master_service.plan(f.project_id, f.input, "repair-format")
    assert result["status"] == "completed"
    assert result["modules"][0]["styleTemplateId"] == "product-commerce-visual"
    assert len(f.master.calls) == 2
    correction = json.loads(f.master.calls[1].user_prompt)["correction"]
    assert correction["previousOutput"] == invalid
    assert correction["validationErrors"]
    assert len(result["snapshot"]["modelAttempts"]) == 2
    assert result["snapshot"]["modelAttempts"][1]["userPrompt"] == f.master.calls[1].user_prompt
    assert (await f.master_service.plan(f.project_id, f.input, "repair-format"))["id"] == result["id"]
    assert len(f.master.calls) == 2


@pytest.mark.asyncio
async def test_provider_outage_does_not_trigger_format_correction():
    f = await fixture()
    async def unavailable(request):
        f.master.calls.append(request)
        raise AppError("MODULE_PLANNER_UNAVAILABLE", "unavailable", 503)
    f.master.plan_modules = unavailable
    with pytest.raises(AppError) as exc:
        await f.master_service.plan(f.project_id, f.input, "outage")
    assert exc.value.code == "MODULE_PLANNER_UNAVAILABLE"
    assert len(f.master.calls) == 1


@pytest.mark.asyncio
async def test_historical_master_snapshot_without_style_choice_still_loads():
    f = await fixture()
    old = output()
    for module in old["modules"]:
        for field in ("styleTemplateId", "bigIdea", "visualMechanism"):
            module.pop(field)
    record, _ = await f.master_repo.create(f.workspace_id, f.project_id, "historical", "old",
        dict(mode="suite", status="completed", **old))
    snapshot = await f.master_service.snapshot(f.project_id, UUID(record["id"]), "suite")
    assert snapshot["modules"] == old["modules"]
    assert f.master.calls == []


@pytest.mark.asyncio
async def test_suite_accepts_six_modules_through_compile_and_repository():
    f = await _fixture()
    req = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids, market_id="taobao",
        model_id="gpt-image-2-5", style_id="minimal", aspect_ratio="3:4", resolution="标准 1K",
        output_language="中文", modules=[SuitePlanModuleInput(m, 1) for m in
            ["suite-hero", "suite-benefit", "suite-scene", "suite-angle", "suite-mood", "suite-detail"]])
    plan = await f.service.compile_plan(f.project_id, req, "six")
    detail = await f.plans.get_plan_detail(plan.id, f.workspace_id, f.project_id)
    assert len(detail.modules) == 6
    assert len(f.compiler.requests) == 6


@pytest.mark.asyncio
async def test_provider_posts_images_and_parses_master_output_without_module_prompt_fields():
    from backend.app.providers.openai_compatible import OpenAICompatibleModulePlanner
    from backend.app.application.module_planning_service import ModuleMasterRequest
    import json
    def handle(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert len(payload["messages"][1]["content"]) == 3
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(output())}}]})
    provider = OpenAICompatibleModulePlanner(base_url="https://test.invalid", api_key="test-only",
        model="fake", timeout_ms=1000, transport=httpx.MockTransport(handle))
    assert await provider.plan_modules(ModuleMasterRequest("system", "user", [b"a", b"b"], ["image/png"]*2)) == output()


@pytest.mark.asyncio
async def test_http_master_plan_can_be_recovered_and_six_module_schema_is_accepted():
    from backend.app.main import create_app
    from backend.app.core.config import Settings
    from backend.app.repository import InMemoryRepository
    from backend.app.schemas import SuitePlanCompileInput, SuitePlanOrderPatchInput, SuitePlanConfirmInput
    f = await fixture()
    app = create_app(Settings(_env_file=None), repository=InMemoryRepository(), module_planning_service=f.master_service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/projects/{f.project_id}/module-plans"
        response = await client.post(url, json=f.input.model_dump(mode="json"), headers={"Idempotency-Key":"api"})
        assert response.status_code == 201, response.text
        latest = await client.get(url + "/latest?mode=suite")
        assert latest.json()["data"]["id"] == response.json()["data"]["id"]
        assert (await client.get(url + "/latest?mode=unknown")).status_code == 400
    data = dict(sourceAssetIds=f.source_asset_ids,marketId="taobao",modelId="m",styleId="s",
        aspectRatio="3:4",resolution="1K",outputLanguage="中文",modules=[{"moduleId":str(i),"resultCount":1} for i in range(6)])
    assert len(SuitePlanCompileInput(**data).modules) == 6
    assert len(SuitePlanOrderPatchInput(expectedPlanRevision=1,moduleIds=[uuid4() for _ in range(6)]).moduleIds) == 6
    assert len(SuitePlanConfirmInput(expectedPlanRevision=1,moduleTaskPrompts={str(i):"prompt" for i in range(6)}).moduleTaskPrompts) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hero", "suite"])
async def test_builtin_skill_is_selected_by_mode_and_legacy_binding_is_ignored(mode):
    from pathlib import Path
    from hashlib import sha256
    f = await fixture(mode)
    published = await f.config.get_published()
    published.content["plannerBindings"] = {mode: {"promptTemplateId": str(uuid4()), "promptVersionId": str(uuid4())}}
    async def old_published():
        return published
    f.config.get_published = old_published
    result = await f.master_service.plan(f.project_id, f.input, "builtin-skill")
    content = (Path(__file__).parents[1] / "app" / "skills" / f"{mode}-planning-master" / "SKILL.md").read_text(encoding="utf-8")
    assert f.master.calls[0].system_prompt == content + "\n\n" + STYLE_LIBRARY_PLANNING_RULES
    assert result["snapshot"]["skill"] == {"name": f"{mode}-planning-master", "source": "builtin_skill", "contentSha256": sha256(content.encode("utf-8")).hexdigest()}


@pytest.mark.asyncio
async def test_missing_builtin_skill_fails_without_model_call(monkeypatch):
    from pathlib import Path
    f = await fixture()
    def missing(*args, **kwargs):
        raise FileNotFoundError("skill missing")
    monkeypatch.setattr(Path, "read_text", missing)
    with pytest.raises(AppError) as error:
        await f.master_service.plan(f.project_id, f.input, "missing-skill")
    assert error.value.code == "MODULE_PLANNER_SKILL_UNAVAILABLE"
    assert f.master.calls == []


@pytest.mark.asyncio
async def test_config_ignores_removed_planner_binding_without_resolving_template():
    f = await fixture()
    draft = await f.config.get_draft()
    draft.content["plannerBindings"] = {"hero": {"promptTemplateId": str(uuid4()), "promptVersionId": str(uuid4())}}
    await f.config.replace_draft(draft.content, draft.base_version_no)
    published = await f.config.publish()
    assert "plannerBindings" not in published.content


@pytest.mark.asyncio
async def test_master_brief_flows_into_hero_modules_and_style_without_losing_manual_edits():
    from backend.tests.test_batch_generation_compile_service import _fixture as hero_fixture, _input
    from backend.app.application.batch_generation_service import BatchHeroModuleInput
    f = await hero_fixture()
    master = ModulePlanningService(MemoryModulePlanningRepository(), f.projects, f.storage,
        f.config, f.prompts, f.service.identity_provider, Planner(output("hero")))
    payload = ModulePlanInput(mode="hero", sourceAssetIds=[f.source_asset_id], marketId="taobao",
        aspectRatio="1:1", outputLanguage="中文", brief="展示按键，暖灰色视觉风格")
    outline = await master.plan(f.project_id, payload, "hero-master")
    f.service.module_planning = master
    modules = [BatchHeroModuleInput(m["moduleId"], m["resultCount"], m["moduleParameters"]) for m in outline["modules"]]
    modules[0].module_parameters[-1]["value"] = "手动微调：商品靠右"
    request = replace(_input(f.source_asset_id), modules=modules, module_plan_id=UUID(outline["id"]))
    batch = await f.service.compile_prompt_batch(f.project_id, request, "hero-master-compile")
    detail = await f.repository.get_batch_detail(batch.id, f.workspace_id)
    assert detail.batch.snapshot["planningMaster"]["id"] == outline["id"]
    assert "手动微调：商品靠右" in f.compiler.requests[0].user_prompt
    assert "暖灰色视觉风格" in f.compiler.requests[0].user_prompt


@pytest.mark.asyncio
async def test_inflight_replay_does_not_call_model_twice():
    import asyncio
    f = await fixture()
    entered, released = asyncio.Event(), asyncio.Event()
    original = f.master.plan_modules
    async def blocked(request):
        entered.set()
        await released.wait()
        return await original(request)
    f.master.plan_modules = blocked
    pending = asyncio.create_task(f.master_service.plan(f.project_id, f.input, "concurrent"))
    await entered.wait()
    try:
        replay = await f.master_service.plan(f.project_id, f.input, "concurrent")
        assert replay["status"] == "planning"
    finally:
        released.set()
    completed = await pending
    assert replay["id"] == completed["id"]
    assert len(f.master.calls) == 1


@pytest.mark.asyncio
async def test_abandoned_plan_is_failed_on_recovery_without_model_call():
    from datetime import datetime, timezone, timedelta
    f = await fixture()
    record, _ = await f.master_repo.create(f.workspace_id, f.project_id, "stale", "fingerprint",
        dict(mode="suite", status="planning"))
    f.master_repo.records[UUID(record["id"])]["value"]["createdAt"] = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    recovered = await f.master_service.latest(f.project_id, "suite")
    assert recovered["status"] == "failed"
    assert recovered["error"]["code"] == "MODULE_PLANNER_INTERRUPTED"
    assert f.master.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(401, "UNAUTHORIZED"), (402, "QUOTA_EXHAUSTED"), (429, "QUOTA_EXHAUSTED"), (500, "FAILED")])
async def test_master_provider_errors_are_actionable_without_exposing_upstream_secrets(status, code):
    from backend.app.providers.openai_compatible import OpenAICompatibleModulePlanner
    from backend.app.application.module_planning_service import ModuleMasterRequest
    provider = OpenAICompatibleModulePlanner(base_url="https://test.invalid", api_key="hidden-key",
        model="fake", timeout_ms=1000, transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"error": "hidden-key upstream details"})))
    with pytest.raises(AppError) as raised:
        await provider.plan_modules(ModuleMasterRequest("system", "user", [b"a"], ["image/png"]))
    assert raised.value.code == f"MODULE_PLANNER_{code}"
    assert "hidden-key" not in str(raised.value)


@pytest.mark.asyncio
async def test_cancelled_call_keeps_frozen_input_and_failed_status():
    import asyncio
    f = await fixture()
    entered = asyncio.Event()
    async def blocked(request):
        entered.set()
        await asyncio.Event().wait()
    f.master.plan_modules = blocked
    task = asyncio.create_task(f.master_service.plan(f.project_id, f.input, "cancel"))
    await entered.wait()
    running = await f.master_service.latest(f.project_id, "suite")
    assert running["snapshot"]["userPrompt"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    failed = await f.master_service.latest(f.project_id, "suite")
    assert failed["status"] == "failed"
    assert failed["snapshot"] == running["snapshot"]


@pytest.mark.asyncio
async def test_hero_master_respects_existing_eight_module_compile_limit():
    f = await fixture("hero")
    draft = await f.config.get_draft()
    extra = {**draft.content["heroModules"][0], "id": "hero-extra", "label": "额外模块"}
    draft.content["heroModules"].append(extra)
    draft.content["heroBindings"]["hero-extra"] = None
    await f.config.replace_draft(draft.content, draft.base_version_no)
    published = await f.config.publish()
    f.master.result["modules"] = [{**deepcopy(output("hero")["modules"][0]), "moduleId": module["id"]}
                                  for module in published.content["heroModules"]]
    with pytest.raises(AppError) as raised:
        await f.master_service.plan(f.project_id, f.input, "too-many-hero")
    assert raised.value.code == "MODULE_PLANNER_INVALID_RESPONSE"
