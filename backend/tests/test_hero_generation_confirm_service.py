from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image

from backend.app.application.generation_config_service import GenerationConfigService
from backend.app.application.hero_generation_ports import ImageEditResult
from backend.app.application.hero_generation_service import (
    HeroGenerationService,
    HeroPromptCompilationInput,
)
from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.ports import SystemClock
from backend.app.application.project_asset_service import ProjectAssetService
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository
from backend.app.hero_generation_repository import InMemoryHeroGenerationRepository
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage
from backend.app.prompt_repository import MemoryPromptRepository


class V2Compiler:
    async def compile(self, _request):
        return {
            "imagePrompt": (
                "黑色耳机，三分之四视角，主体居中，右侧留白。"
                "整体为柔和侧光，浅灰背景。无水印、无额外道具。"
            ),
            "copySummary": "突出黑色耳机",
            "visualDirection": "主体居中",
            "exactCopy": ["沉浸聆听"],
            "visibleFacts": ["黑色耳机"],
            "unconfirmedItems": ["续航未知"],
        }


class RecordingImageEditor:
    def __init__(self, image_bytes: bytes) -> None:
        self.image_bytes = image_bytes
        self.requests = []

    def describe_request(self, request):
        return {
            "model": "gpt-image-2",
            "endpoint": "/v1/images/edits",
            "size": "1024x1024",
            "quality": "medium",
            "n": 1,
            "responseFormat": "b64_json",
            "sourceImageCount": 1,
        }

    async def edit(self, request):
        self.requests.append(request)
        return ImageEditResult(
            image_bytes=self.image_bytes,
            image_mime_type="image/png",
            provider_request=self.describe_request(request),
        )


@pytest.mark.asyncio
async def test_confirm_composes_frozen_cards_and_creates_generated_project_asset() -> None:
    fixture = await _fixture()
    task = await fixture.service.compile_prompt(
        fixture.project.id, _compile_input(fixture.source.id), "compile"
    )

    completed = await fixture.service.confirm_generation(
        fixture.project.id, task.id, task_prompt=task.compiled_task_prompt, idempotency_key="confirm",
    )
    assert completed.status == "succeeded"
    assert completed.compiled_task_prompt == task.compiled_task_prompt
    assert completed.confirmed_task_prompt == task.compiled_task_prompt
    assert completed.final_prompt == task.compiled_task_prompt
    assert len(completed.final_prompt_sha256 or "") == 64
    assert completed.provider_request == fixture.editor.describe_request(
        fixture.editor.requests[0]
    )
    assert len(fixture.editor.requests) == 1
    provider_request = fixture.editor.requests[0]
    assert provider_request.image_bytes == fixture.source_bytes
    assert provider_request.aspect_ratio == "1:1"
    assert provider_request.resolution == "标准 1K"
    generated = await fixture.projects.get_asset(
        completed.generated_asset_id, fixture.workspace_id
    )
    assert generated is not None
    assert generated.kind == "generated"
    assert generated.source_asset_id == fixture.source.id
    assert generated.generation_snapshot_id == task.id
    preview = await fixture.assets.get_preview(fixture.project.id, generated.id)
    assert preview.data == fixture.generated_bytes


@pytest.mark.asyncio
async def test_duplicate_confirmation_returns_same_result_without_second_provider_call() -> None:
    fixture = await _fixture()
    task = await fixture.service.compile_prompt(
        fixture.project.id, _compile_input(fixture.source.id), "compile"
    )

    first = await fixture.service.confirm_generation(
        fixture.project.id, task.id, task_prompt=None, idempotency_key="confirm"
    )
    replay = await fixture.service.confirm_generation(
        fixture.project.id, task.id, task_prompt=None, idempotency_key="confirm"
    )

    assert replay.id == first.id
    assert replay.generated_asset_id == first.generated_asset_id
    assert len(fixture.editor.requests) == 1
    assert len(await fixture.projects.list_assets(fixture.project.id, fixture.workspace_id)) == 2


@pytest.mark.asyncio
async def test_v2_confirmation_rejects_prompt_mutation_and_recomposes_from_snapshot() -> None:
    fixture = await _fixture(planner_version="v2", compiler=V2Compiler())
    task = await fixture.service.compile_prompt(
        fixture.project.id, _compile_input(fixture.source.id), "compile-v2"
    )

    with pytest.raises(AppError) as changed:
        await fixture.service.confirm_generation(
            fixture.project.id,
            task.id,
            task_prompt=task.compiled_task_prompt + " 绕过服务端构图",
            idempotency_key="confirm-changed",
        )
    assert changed.value.code == "HERO_GENERATION_V2_PROMPT_IMMUTABLE"
    assert fixture.editor.requests == []

    completed = await fixture.service.confirm_generation(
        fixture.project.id,
        task.id,
        task_prompt=task.compiled_task_prompt,
        idempotency_key="confirm-v2",
    )
    assert completed.confirmed_task_prompt == task.compiled_task_prompt
    assert completed.final_prompt.strip()
    assert completed.final_prompt_sha256 == __import__("hashlib").sha256(
        completed.final_prompt.encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_confirmation_rejects_wrong_project_and_illegal_state_without_provider_call() -> None:
    fixture = await _fixture()
    task = await fixture.service.compile_prompt(
        fixture.project.id, _compile_input(fixture.source.id), "compile"
    )
    other_project = await fixture.projects.create_project("其他项目", fixture.workspace_id)

    with pytest.raises(AppError) as wrong_project:
        await fixture.service.confirm_generation(
            other_project.id, task.id, task_prompt=None, idempotency_key="wrong-project"
        )
    await fixture.tasks.fail(task.id, fixture.workspace_id, "TEST_FAILURE", "test failure")
    with pytest.raises(AppError) as invalid_state:
        await fixture.service.confirm_generation(
            fixture.project.id, task.id, task_prompt=None, idempotency_key="failed-task"
        )

    assert wrong_project.value.code == "HERO_GENERATION_NOT_FOUND"
    assert invalid_state.value.code == "HERO_GENERATION_INVALID_STATE"
    assert fixture.editor.requests == []


@pytest.mark.asyncio
async def test_generated_asset_metadata_failure_deletes_new_object_and_marks_task_failed() -> None:
    class FailingGeneratedRepository(InMemoryProjectRepository):
        fail_generated = False

        async def create_asset(self, project_id, object_id, kind, **kwargs):
            if kind == "generated" and self.fail_generated:
                raise RuntimeError("generated asset insert failed")
            return await super().create_asset(project_id, object_id, kind, **kwargs)

    repository = FailingGeneratedRepository()
    fixture = await _fixture(repository)
    task = await fixture.service.compile_prompt(
        fixture.project.id, _compile_input(fixture.source.id), "compile"
    )
    repository.fail_generated = True

    with pytest.raises(RuntimeError, match="generated asset insert failed"):
        await fixture.service.confirm_generation(
            fixture.project.id, task.id, task_prompt=None, idempotency_key="confirm"
        )

    failed = await fixture.tasks.get_task(task.id, fixture.workspace_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "HERO_GENERATION_PERSIST_FAILED"
    assert len(fixture.storage.objects) == 1
    assert next(iter(fixture.storage.objects.values())).data == fixture.source_bytes
    assert len(await fixture.projects.list_assets(fixture.project.id, fixture.workspace_id)) == 1


@pytest.mark.asyncio
async def test_task_completion_failure_deletes_generated_asset_and_marks_task_failed() -> None:
    class FailingCompleteRepository(InMemoryHeroGenerationRepository):
        async def complete(self, task_id, workspace_id, generated_asset_id):
            raise RuntimeError("task completion failed")

    fixture = await _fixture(task_repository=FailingCompleteRepository())
    task = await fixture.service.compile_prompt(
        fixture.project.id, _compile_input(fixture.source.id), "compile"
    )

    with pytest.raises(RuntimeError, match="task completion failed"):
        await fixture.service.confirm_generation(
            fixture.project.id, task.id, task_prompt=None, idempotency_key="confirm"
        )

    failed = await fixture.tasks.get_task(task.id, fixture.workspace_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "HERO_GENERATION_PERSIST_FAILED"
    assert len(await fixture.projects.list_assets(fixture.project.id, fixture.workspace_id)) == 1
    assert len(fixture.storage.objects) == 1
    assert next(iter(fixture.storage.objects.values())).data == fixture.source_bytes


class _Fixture:
    pass


async def _fixture(repository=None, task_repository=None, *, planner_version="v1", compiler=None):
    result = _Fixture()
    result.workspace_id = UUID(int=11)
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=10), result.workspace_id, "owner")
    )
    result.projects = repository or InMemoryProjectRepository()
    result.storage = MemoryProjectAssetStorage()
    result.assets = ProjectAssetService(result.projects, result.storage, identity)
    result.prompts = MemoryPromptRepository()
    result.tasks = task_repository or InMemoryHeroGenerationRepository()
    result.config = GenerationConfigService(
        InMemoryGenerationConfigRepository(),
        identity,
        MemoryIdempotencyStore(),
        SystemClock(),
        prompt_repository=result.prompts,
    )
    result.project = await result.projects.create_project("耳机主图", result.workspace_id)
    result.source_bytes = _png((12, 8), (10, 20, 30))
    result.source = await result.assets.upload_asset(
        result.project.id,
        "source",
        result.source_bytes,
        "image/png",
        "headphones.png",
    )
    result.generated_bytes = _png((16, 16), (100, 120, 140))
    result.editor = RecordingImageEditor(result.generated_bytes)
    result.service = HeroGenerationService(
        project_repository=result.projects,
        project_storage=result.storage,
        project_asset_service=result.assets,
        generation_config_service=result.config,
        prompt_repository=result.prompts,
        task_repository=result.tasks,
        prompt_compiler=compiler or V2Compiler(),
        image_editor=result.editor,
        identity_provider=identity,
        provider_model="gpt-image-2",
    )
    return result


def _compile_input(source_asset_id: UUID) -> HeroPromptCompilationInput:
    return HeroPromptCompilationInput(
        source_asset_id=source_asset_id,
        market_id="taobao",
        model_id="gpt-image-2-5",
        style_id="precision",
        module_id="hero-kv",
        aspect_ratio="1:1",
        resolution="标准 1K",
        output_language="中文",
        result_count=1,
    )


def _png(size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()
