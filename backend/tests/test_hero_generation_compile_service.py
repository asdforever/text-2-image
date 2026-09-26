from copy import deepcopy
from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image

from backend.app.application.generation_config_service import GenerationConfigService
from backend.app.application.hero_generation_service import (
    HeroGenerationService,
    HeroPromptCompilationInput,
)
from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.ports import SystemClock
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository
from backend.app.hero_generation_repository import InMemoryHeroGenerationRepository
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage, project_asset_object_key
from backend.app.prompt_repository import MemoryPromptRepository
from backend.app.storage import StoredObject


class RecordingV2Compiler:
    def __init__(self) -> None:
        self.requests = []

    async def compile(self, request):
        self.requests.append(request)
        return {
            "imagePrompt": (
                "黑色耳机主体，三分之四视角，主体居中，右侧留白，右侧标题安全区。"
                "整体为柔和侧光，干净浅灰背景。无水印、无额外道具。"
            ),
            "copySummary": "突出黑色耳机的可见结构",
            "visualDirection": "主体居中，右侧留白",
            "exactCopy": ["沉浸聆听"],
            "visibleFacts": ["商品为黑色"],
            "unconfirmedItems": ["无法确认灵敏度"],
        }


class ValidatingImageEditor:
    def describe_request(self, request):
        if request.aspect_ratio != "1:1" or request.resolution != "标准 1K":
            raise AppError(
                "IMAGE_PROVIDER_PARAMETERS_UNSUPPORTED",
                "image size is not supported by the configured provider",
                400,
            )
        return {"size": "1024x1024", "n": 1}

    async def edit(self, _request):
        raise AssertionError("compile must not call the image provider")


@pytest.mark.asyncio
async def test_compile_creates_awaiting_task_from_source_and_published_configuration() -> None:
    fixture = await _fixture()
    module_template, module_version = await fixture.prompts.create_template_with_version(
        code="hero-kv-planner",
        name="首屏 KV 规划师",
        kind="generation",
        kind_name="图片生成",
        execution_target="image",
        body="你是专业提示词规划师，只能依据图片可见事实和用户明确参数。",
        user_prompt_template="请依据以下结构化任务规划一张首屏主图：{{structured_input}}",
    )
    published = await fixture.config.get_published()
    draft = deepcopy(published.content)
    draft["heroBindings"]["hero-kv"] = {
        "promptTemplateId": str(module_template.id),
        "promptVersionId": str(module_version.id),
    }
    await fixture.config.replace_draft(draft, published.version_no)
    published = await fixture.config.publish()

    task = await fixture.service.compile_prompt(
        fixture.project_id,
        _input(fixture.source_asset_id),
        "compile-once",
    )

    assert task.status == "awaiting_confirmation"
    assert task.snapshot["plannerVersion"] == "v2"
    assert task.compiled_task_prompt.strip()
    assert task.compiler_output["visibleFacts"] == ["商品为黑色"]
    assert len(fixture.compiler.requests) == 1
    assert fixture.compiler.requests[0].image_bytes == fixture.source_bytes
    assert task.snapshot["sourceAsset"]["sha256"] == fixture.source_sha256
    assert task.snapshot["modulePlanning"]["rendererVersion"]



@pytest.mark.asyncio
async def test_v2_compile_uses_one_module_call_and_freezes_server_rendered_result() -> None:
    fixture = await _fixture(planner_version="v2")
    fixture.compiler = RecordingV2Compiler()
    fixture.service.prompt_compiler = fixture.compiler

    task = await fixture.service.compile_prompt(
        fixture.project_id,
        _input(fixture.source_asset_id),
        "v2-compile-once",
    )

    assert task.status == "awaiting_confirmation"
    assert task.snapshot["plannerVersion"] == "v2"
    assert task.snapshot["styleSeed"]["seedId"] == "builtin:precision"
    assert task.snapshot["styleSeed"]["sha256"]
    assert task.snapshot["selection"]["customStyle"] == "保持背景略带冷灰"
    assert task.snapshot["modulePlanning"]["rendererVersion"]
    assert "主体居中，右侧留白" in task.snapshot["modulePlanning"]["result"]["imagePrompt"]
    assert task.compiler_output["visibleFacts"] == ["商品为黑色"]
    assert task.compiled_task_prompt.strip()
    # 自定义风格与模块参数作为编译输入交给模型，不再拼进渲染结果
    assert "保持背景略带冷灰" in fixture.compiler.requests[0].user_prompt
    assert "灵敏度" in fixture.compiler.requests[0].user_prompt
    assert len(fixture.compiler.requests) == 1
    assert fixture.compiler.requests[0].planner_version == "v2"


@pytest.mark.asyncio
async def test_compile_replays_same_task_without_reading_image_or_calling_compiler_again() -> None:
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)

    first = await fixture.service.compile_prompt(fixture.project_id, request, "same-key")
    await fixture.storage.delete(fixture.source_storage_key)
    replay = await fixture.service.compile_prompt(fixture.project_id, request, "same-key")

    assert replay.id == first.id
    assert replay.status == "awaiting_confirmation"
    assert len(fixture.compiler.requests) == 1


@pytest.mark.asyncio
async def test_compile_rejects_draft_only_selection_without_creating_task() -> None:
    fixture = await _fixture()
    published = await fixture.config.get_published()
    draft = deepcopy(published.content)
    draft["markets"].append(
        {
            "id": "draft-market",
            "label": "草稿平台",
            "marketScope": "domestic",
            "platforms": "草稿平台",
            "guidance": "仅存在草稿",
            "defaultLanguage": "中文",
        }
    )
    draft["marketBindings"]["draft-market"] = None
    await fixture.config.replace_draft(draft, published.version_no)
    request = _input(fixture.source_asset_id)
    request = HeroPromptCompilationInput(**{**request.__dict__, "market_id": "draft-market"})

    with pytest.raises(AppError) as raised:
        await fixture.service.compile_prompt(fixture.project_id, request, "draft-selection")

    assert raised.value.code == "GENERATION_CONFIG_SELECTION_INVALID"
    assert fixture.compiler.requests == []


@pytest.mark.asyncio
async def test_compile_rejects_asset_from_another_project() -> None:
    fixture = await _fixture()
    other_project = await fixture.projects.create_project("其他项目", fixture.workspace_id)
    other_object = await fixture.projects.create_object(
        fixture.workspace_id,
        "other/source.png",
        "source.png",
        "image/png",
        len(fixture.source_bytes),
        12,
        8,
        fixture.source_sha256,
    )
    other_asset = await fixture.projects.create_asset(other_project.id, other_object.id, "source")

    with pytest.raises(AppError) as raised:
        await fixture.service.compile_prompt(
            fixture.project_id,
            _input(other_asset.id),
            "cross-project",
        )

    assert raised.value.code == "INVALID_SOURCE_ASSET"
    assert fixture.compiler.requests == []


@pytest.mark.asyncio
async def test_compile_rejects_multiple_results_for_stage_3a() -> None:
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    request = HeroPromptCompilationInput(**{**request.__dict__, "result_count": 2})

    with pytest.raises(AppError) as raised:
        await fixture.service.compile_prompt(fixture.project_id, request, "two-results")

    assert raised.value.code == "HERO_GENERATION_SINGLE_RESULT_REQUIRED"
    assert fixture.compiler.requests == []


@pytest.mark.asyncio
async def test_compile_rejects_unsupported_provider_parameters_before_prompt_compilation() -> None:
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    request = HeroPromptCompilationInput(**{**request.__dict__, "aspect_ratio": "9:16"})

    with pytest.raises(AppError) as raised:
        await fixture.service.compile_prompt(
            fixture.project_id, request, "unsupported-ratio"
        )

    assert raised.value.code == "IMAGE_PROVIDER_PARAMETERS_UNSUPPORTED"
    assert fixture.compiler.requests == []
    assert await fixture.tasks.get_by_compile_idempotency(
        fixture.workspace_id, "unsupported-ratio"
    ) is None


@pytest.mark.asyncio
async def test_unexpected_compiler_failure_marks_task_failed_with_safe_error() -> None:
    fixture = await _fixture()

    async def fail_compile(_request):
        raise RuntimeError("secret upstream exception")

    fixture.compiler.compile = fail_compile

    with pytest.raises(AppError) as raised:
        await fixture.service.compile_prompt(
            fixture.project_id, _input(fixture.source_asset_id), "compiler-crash"
        )

    assert raised.value.code == "PROMPT_COMPILER_FAILED"
    task = await fixture.tasks.get_by_compile_idempotency(
        fixture.workspace_id, "compiler-crash"
    )
    assert task is not None
    assert task.status == "failed"
    assert task.error_message == "prompt compiler request failed"
    assert "secret" not in task.error_message


class _Fixture:
    pass


async def _fixture(*, planner_version: str = "v1"):
    result = _Fixture()
    result.workspace_id = UUID(int=11)
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=10), result.workspace_id, "owner")
    )
    result.projects = InMemoryProjectRepository()
    result.storage = MemoryProjectAssetStorage()
    result.prompts = MemoryPromptRepository()
    result.tasks = InMemoryHeroGenerationRepository()
    result.compiler = RecordingV2Compiler()
    result.config = GenerationConfigService(
        InMemoryGenerationConfigRepository(),
        identity,
        MemoryIdempotencyStore(),
        SystemClock(),
        prompt_repository=result.prompts,
    )
    project = await result.projects.create_project("耳机主图", result.workspace_id)
    result.project_id = project.id
    result.source_bytes = _png_bytes()
    result.source_sha256 = __import__("hashlib").sha256(result.source_bytes).hexdigest()
    object_id = UUID(int=31)
    result.source_storage_key = project_asset_object_key(
        result.workspace_id, project.id, object_id, "image/png"
    )
    await result.storage.put(
        StoredObject(result.source_storage_key, result.source_bytes, "image/png")
    )
    source_object = await result.projects.create_object(
        result.workspace_id,
        result.source_storage_key,
        "headphones.png",
        "image/png",
        len(result.source_bytes),
        12,
        8,
        result.source_sha256,
        object_id=object_id,
    )
    source_asset = await result.projects.create_asset(project.id, source_object.id, "source")
    result.source_asset_id = source_asset.id
    result.service = HeroGenerationService(
        project_repository=result.projects,
        project_storage=result.storage,
        generation_config_service=result.config,
        prompt_repository=result.prompts,
        task_repository=result.tasks,
        prompt_compiler=result.compiler,
        image_editor=ValidatingImageEditor(),
        identity_provider=identity,
        provider_model="gpt-image-2",
    )
    return result


def _input(source_asset_id: UUID) -> HeroPromptCompilationInput:
    return HeroPromptCompilationInput(
        source_asset_id=source_asset_id,
        market_id="taobao",
        model_id="gpt-image-2-5",
        style_id="precision",
        module_id="hero-kv",
        aspect_ratio="1:1",
        resolution="标准 1K",
        output_language="中文",
        custom_style="保持背景略带冷灰",
        module_parameters=[{"key": "灵敏度", "value": "8000 DPI"}],
        result_count=1,
    )


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), (10, 20, 30)).save(output, format="PNG")
    return output.getvalue()
