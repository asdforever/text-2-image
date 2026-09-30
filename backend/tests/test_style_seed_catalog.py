from dataclasses import replace
from uuid import UUID

import pytest

from backend.app.application.style_seed_catalog import import_style_seeds, resolve_marketplace_style_seed, style_template_code
from backend.app.application.module_planning_v2 import resolve_style_seed
from backend.app.application.prompt_usage import require_image_prompt
from backend.app.core.errors import AppError
from backend.app.generation_config_catalog import DEFAULT_STYLE_CATEGORIES
from backend.app.prompt_service import PromptService
from backend.app.prompt_repository import MemoryPromptRepository


@pytest.mark.asyncio
async def test_import_all_seeds_is_idempotent_and_preserves_user_defaults():
    repo = MemoryPromptRepository()
    service = PromptService(repo)
    report = await import_style_seeds(service)
    styles = [style for category in DEFAULT_STYLE_CATEGORIES for style in category["styles"]]
    assert len(report["created"]) == len(styles) == 21
    category = (await repo.list_categories())[0]
    assert category.name == "风格库"
    for style in styles:
        template = await repo.get_template_by_code(style_template_code(style["id"]))
        version = await repo.resolve_version(template.id)
        assert template.category_id == category.id
        assert version.body == resolve_style_seed(style).text
        with pytest.raises(AppError):
            require_image_prompt(version)
    template = await repo.get_template_by_code(style_template_code("minimal"))
    saved = await service.create_version(template.id, template.default_version_id, {"body": "用户修改：米白背景与自然侧光"})
    report = await import_style_seeds(service)
    assert report["created"] == []
    assert len(report["existing"]) == 21
    assert (await repo.get_template(template.id)).default_version_id == saved.version.id
    assert len(await repo.list_versions(template.id)) == 2


@pytest.mark.asyncio
async def test_resolver_freezes_default_version_and_does_not_ignore_invalid_marketplace_content():
    repo = MemoryPromptRepository()
    service = PromptService(repo)
    await import_style_seeds(service)
    style = DEFAULT_STYLE_CATEGORIES[0]["styles"][0]
    first = await resolve_marketplace_style_seed(style, repo)
    before = first.to_snapshot()
    template = await repo.get_template_by_code(style_template_code(style["id"]))
    saved = await service.create_version(template.id, template.default_version_id, {"body": "新的暖色风格"})
    second = await resolve_marketplace_style_seed(style, repo)
    assert second.text == "新的暖色风格"
    assert second.prompt_version_id == str(saved.version.id)
    assert second.sha256 != first.sha256
    assert first.to_snapshot() == before
    # Memory repository stores mutable records; emulate selecting the earlier default.
    template.default_version_id = UUID(first.prompt_version_id)
    assert (await resolve_marketplace_style_seed(style, repo)).text == first.text
    await service.create_version(template.id, template.default_version_id, {"body": " "})
    with pytest.raises(AppError):
        await resolve_marketplace_style_seed(style, repo)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["regular", "professional"])
async def test_hero_new_compilations_use_marketplace_body_and_previous_batch_stays_frozen(mode):
    from backend.tests.test_batch_generation_compile_service import _fixture, _input
    f = await _fixture()
    service = PromptService(f.service.prompt_repository)
    await import_style_seeds(service)
    request = replace(_input(f.source_asset_id), creation_mode=mode)
    template = await service.repository.get_template_by_code(style_template_code(request.style_id))
    original = await f.service.compile_prompt_batch(f.project_id, request, f"first-{mode}")
    before = (await f.repository.get_batch_detail(original.id, f.workspace_id)).batch.snapshot["styleSeed"]
    saved = await service.create_version(template.id, template.default_version_id, {"body": "MARKETPLACE_STYLE 独特米白色背景与侧面柔光"})
    batch = await f.service.compile_prompt_batch(f.project_id, request, f"next-{mode}")
    detail = await f.repository.get_batch_detail(batch.id, f.workspace_id)
    assert detail.batch.snapshot["styleSeed"]["promptVersionId"] == str(saved.version.id)
    assert "MARKETPLACE_STYLE" in detail.batch.snapshot["styleSeed"]["text"]
    if mode == "regular":
        assert "MARKETPLACE_STYLE" in detail.module_tasks[0].compiled_task_prompt
    else:
        assert "MARKETPLACE_STYLE" in f.compiler.requests[-1].user_prompt
    replay = await f.service.compile_prompt_batch(f.project_id, request, f"first-{mode}")
    assert (await f.repository.get_batch_detail(replay.id, f.workspace_id)).batch.snapshot["styleSeed"] == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["regular", "professional"])
async def test_suite_compilation_uses_marketplace_style_version(mode):
    from backend.tests.test_suite_planning_service import _fixture
    from backend.app.application.suite_planning_service import SuitePlanCompilationInput, SuitePlanModuleInput
    f = await _fixture()
    service = PromptService(f.service.prompt_repository)
    await import_style_seeds(service)
    template = await service.repository.get_template_by_code(style_template_code("minimal"))
    saved = await service.create_version(template.id, template.default_version_id, {"body": "SUITE_MARKETPLACE_STYLE 统一米白与浅木色"})
    request = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids, market_id="taobao", model_id="gpt-image-2-5", style_id="minimal", aspect_ratio="3:4", resolution="标准 1K", output_language="中文", creation_mode=mode, modules=[SuitePlanModuleInput("suite-hero", 1, [])])
    plan = await f.service.compile_plan(f.project_id, request, f"style-{mode}")
    detail = await f.plans.get_plan_detail(plan.id, f.workspace_id, f.project_id)
    assert detail.plan.snapshot["styleSeed"]["promptVersionId"] == str(saved.version.id)
    if mode == "regular":
        assert "SUITE_MARKETPLACE_STYLE" in detail.modules[0].compiled_task_prompt
    else:
        assert "SUITE_MARKETPLACE_STYLE" in f.compiler.requests[-1].user_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["regular", "professional"])
async def test_planning_receives_marketplace_style_seed(mode):
    from backend.tests.test_module_planning import fixture
    f = await fixture()
    service = PromptService(f.master_service.prompts)
    await import_style_seeds(service)
    template = await service.repository.get_template_by_code(style_template_code("minimal"))
    saved = await service.create_version(template.id, template.default_version_id, {"body": "PLANNER_MARKET_STYLE 自然光"})
    if mode == "regular":
        f.master.result = {"summary": "商品说明", "modules": [{"taskId": "a", "moduleId": "suite-hero", "taskTitle": "材质", "reason": "解释材质", "suggestedCopy": "纯棉", "moduleParameters": [{"key": "材质", "value": "纯棉"}]}], "warnings": []}
    result = await f.master_service.plan(f.project_id, f.input.model_copy(update={"creationMode": mode}), f"market-planner-{mode}")
    assert "PLANNER_MARKET_STYLE" in f.master.calls[0].user_prompt
    assert str(saved.version.id) in f.master.calls[0].user_prompt
    assert result["status"] == "completed"
