from io import BytesIO
from copy import deepcopy
from uuid import UUID

import pytest
from PIL import Image

from backend.app.application.batch_generation_service import (
    BatchHeroModuleInput,
    BatchHeroPromptCompilationInput,
    BatchHeroPromptCompilationService,
)
from backend.app.application.generation_config_service import GenerationConfigService
from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.ports import SystemClock
from backend.app.batch_generation_repository import InMemoryBatchGenerationRepository
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage, project_asset_object_key
from backend.app.prompt_repository import MemoryPromptRepository
from backend.app.storage import StoredObject


class RecordingV2Compiler:
    def __init__(self) -> None:
        self.requests = []

    async def compile(self, request):
        self.requests.append(request)
        index = len(self.requests)
        return {
            "imagePrompt": (
                f"黑色商品，三分之四视角，构图 {index}，右侧留白。"
                "整体为柔和侧光，浅灰背景。无水印、无额外道具。"
            ),
            "copySummary": f"第 {index} 个任务",
            "visualDirection": f"构图 {index}",
            "exactCopy": [f"卖点 {index}"],
            "visibleFacts": ["图片中有黑色商品"],
            "unconfirmedItems": ["具体规格无法确认"],
        }


class RecordingImageEditor:
    def __init__(self) -> None:
        self.describe_requests = []
        self.edit_requests = []

    def describe_request(self, request):
        self.describe_requests.append(request)
        return {"size": "1024x1024", "n": 1}

    async def edit(self, request):
        self.edit_requests.append(request)
        raise AssertionError("批次提示词编译不得调用图片 Provider")


@pytest.mark.asyncio
async def test_compile_batch_freezes_two_module_reviews_without_creating_images() -> None:
    fixture = await _fixture()

    batch = await fixture.service.compile_prompt_batch(
        fixture.project_id,
        _input(fixture.source_asset_id),
        "batch-compile-once",
    )
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)

    assert batch.status == "awaiting_confirmation"
    assert detail is not None
    assert [(item.module_key, item.requested_image_count) for item in detail.module_tasks] == [
        ("hero-kv", 3),
        ("hero-scene", 2),
    ]
    assert all(item.compiled_task_prompt.strip() for item in detail.module_tasks)
    assert detail.slots == []
    assert len(fixture.compiler.requests) == 2
    assert fixture.editor.edit_requests == []
    assert detail.module_tasks[0].snapshot["constraints"]["style"]["content"]
    assert detail.module_tasks[1].snapshot["modulePlanning"]["rendererVersion"]


@pytest.mark.asyncio
async def test_v2_batch_uses_one_call_per_task_and_freezes_master_outline() -> None:
    fixture = await _fixture(planner_version="v2")
    fixture.compiler = RecordingV2Compiler()
    fixture.service.prompt_compiler = fixture.compiler
    plan_id = UUID(int=808)

    class MasterPlanning:
        async def snapshot(self, _project_id, requested_plan_id, mode):
            assert requested_plan_id == plan_id
            assert mode == "hero"
            return {
                "id": str(plan_id),
                "mode": "hero",
                "status": "completed",
                "planningContractVersion": "commerce-design-v1",
                "sharedVisualDirection": "统一品牌层级并区分两张任务",
                "summary": "两张图分别负责首屏识别与卖点延展",
                "input": {"brief": "避免两张图构图重复"},
                "modules": [
                    {"moduleId": "hero-kv", "taskId": "kv-a", "taskTitle": "建立识别",
                     "designGuideIds": ["visual-hierarchy"], "productPresence": "full",
                     "compositionBrief": "主体居中"},
                    {"moduleId": "hero-kv", "taskId": "kv-b", "taskTitle": "扩展信息",
                     "designGuideIds": ["data-explanation"], "productPresence": "detail",
                     "compositionBrief": "主体偏左"},
                ],
            }

    fixture.service.module_planning = MasterPlanning()
    request = _input(fixture.source_asset_id)
    request = BatchHeroPromptCompilationInput(
        **{
            **request.__dict__,
            "module_plan_id": plan_id,
            "modules": [
                BatchHeroModuleInput("hero-kv", 1, task_id="kv-a"),
                BatchHeroModuleInput("hero-kv", 1, task_id="kv-b"),
            ],
        }
    )

    batch = await fixture.service.compile_prompt_batch(
        fixture.project_id, request, "batch-v2"
    )
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)

    assert batch.snapshot["plannerVersion"] == "v2"
    assert batch.snapshot["planningMaster"]["summary"]
    assert len(fixture.compiler.requests) == 2
    assert detail is not None
    assert [task.module_key for task in detail.module_tasks] == ["kv-a", "kv-b"]
    assert all(task.snapshot["styleSeed"]["seedId"] == "builtin:precision" for task in detail.module_tasks)
    assert [task.snapshot["taskOutline"]["taskId"] for task in detail.module_tasks] == ["kv-a", "kv-b"]
    assert all(task.snapshot["modulePlanning"]["resultSha256"] for task in detail.module_tasks)
    assert "避免两张图构图重复" in fixture.compiler.requests[0].user_prompt
    assert '"taskId":"kv-a"' in fixture.compiler.requests[0].user_prompt
    assert '"taskId":"kv-b"' in fixture.compiler.requests[0].user_prompt
    assert '"outputSchema"' in fixture.compiler.requests[0].user_prompt
    assert '"type":"array"' in fixture.compiler.requests[0].user_prompt
    assert "统一品牌层级并区分两张任务" in fixture.compiler.requests[0].user_prompt
    assert "不得改变固定种子的配色关系与光线逻辑" not in fixture.compiler.requests[0].system_prompt


@pytest.mark.asyncio
async def test_v2_manual_repeated_modules_receive_full_selected_task_context() -> None:
    fixture = await _fixture(planner_version="v2")
    fixture.compiler = RecordingV2Compiler()
    fixture.service.prompt_compiler = fixture.compiler
    request = _input(fixture.source_asset_id)
    request = BatchHeroPromptCompilationInput(
        **{
            **request.__dict__,
            "modules": [
                BatchHeroModuleInput("hero-kv", 1, [{"key": "位置", "value": "居中"}], task_id="manual-a"),
                BatchHeroModuleInput("hero-kv", 1, [{"key": "位置", "value": "偏左"}], task_id="manual-b"),
            ],
        }
    )

    await fixture.service.compile_prompt_batch(
        fixture.project_id, request, "batch-v2-manual"
    )

    first = fixture.compiler.requests[0].user_prompt
    second = fixture.compiler.requests[1].user_prompt
    assert '"currentTaskId":"manual-a"' in first
    assert '"currentTaskId":"manual-b"' in second
    assert '"taskId":"manual-a"' in first and '"taskId":"manual-b"' in first
    assert '"value":"居中"' in first and '"value":"偏左"' in first


@pytest.mark.asyncio
async def test_compile_batch_replay_does_not_read_source_or_compile_again() -> None:
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)

    first = await fixture.service.compile_prompt_batch(
        fixture.project_id, request, "batch-compile-replay"
    )
    await fixture.storage.delete(fixture.source_storage_key)
    replay = await fixture.service.compile_prompt_batch(
        fixture.project_id, request, "batch-compile-replay"
    )

    assert replay.id == first.id
    assert len(fixture.compiler.requests) == 2


@pytest.mark.asyncio
async def test_compile_batch_rejects_invalid_module_count_before_creating_a_batch() -> None:
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    invalid = BatchHeroPromptCompilationInput(
        **{
            **request.__dict__,
            "modules": [BatchHeroModuleInput("hero-kv", 5)],
        }
    )

    with pytest.raises(AppError) as raised:
        await fixture.service.compile_prompt_batch(fixture.project_id, invalid, "invalid-count")

    assert raised.value.code == "BATCH_GENERATION_INVALID_INPUT"
    assert fixture.compiler.requests == []
    assert await fixture.repository.get_by_compile_idempotency(
        fixture.workspace_id, "invalid-count"
    ) is None


@pytest.mark.asyncio
async def test_compile_batch_rejects_draft_only_market_without_creating_a_batch() -> None:
    fixture = await _fixture()
    published = await fixture.config.get_published()
    draft = deepcopy(published.content)
    draft["markets"].append(
        {
            "id": "draft-market",
            "label": "草稿平台",
            "marketScope": "domestic",
            "platforms": "草稿平台",
            "guidance": "仅存在于草稿",
            "defaultLanguage": "中文",
        }
    )
    draft["marketBindings"]["draft-market"] = None
    await fixture.config.replace_draft(draft, published.version_no)
    request = _input(fixture.source_asset_id)
    draft_request = BatchHeroPromptCompilationInput(
        **{**request.__dict__, "market_id": "draft-market"}
    )

    with pytest.raises(AppError) as raised:
        await fixture.service.compile_prompt_batch(
            fixture.project_id, draft_request, "draft-market"
        )

    assert raised.value.code == "GENERATION_CONFIG_SELECTION_INVALID"
    assert fixture.compiler.requests == []
    assert await fixture.repository.get_by_compile_idempotency(
        fixture.workspace_id, "draft-market"
    ) is None


class _Fixture:
    pass


async def _fixture(*, planner_version: str = "v1"):
    fixture = _Fixture()
    fixture.workspace_id = UUID(int=11)
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=10), fixture.workspace_id, "owner")
    )
    fixture.projects = InMemoryProjectRepository()
    fixture.storage = MemoryProjectAssetStorage()
    fixture.prompts = MemoryPromptRepository()
    fixture.repository = InMemoryBatchGenerationRepository()
    fixture.compiler = RecordingV2Compiler()
    fixture.editor = RecordingImageEditor()
    fixture.config = GenerationConfigService(
        InMemoryGenerationConfigRepository(), identity, MemoryIdempotencyStore(), SystemClock(),
        prompt_repository=fixture.prompts,
    )
    project = await fixture.projects.create_project("批量主图", fixture.workspace_id)
    fixture.project_id = project.id
    source_bytes = _png_bytes()
    source_sha256 = __import__("hashlib").sha256(source_bytes).hexdigest()
    object_id = UUID(int=31)
    fixture.source_storage_key = project_asset_object_key(
        fixture.workspace_id, project.id, object_id, "image/png"
    )
    await fixture.storage.put(StoredObject(fixture.source_storage_key, source_bytes, "image/png"))
    source_object = await fixture.projects.create_object(
        fixture.workspace_id, fixture.source_storage_key, "product.png", "image/png",
        len(source_bytes), 12, 8, source_sha256, object_id=object_id,
    )
    source_asset = await fixture.projects.create_asset(project.id, source_object.id, "source")
    fixture.source_asset_id = source_asset.id
    fixture.service = BatchHeroPromptCompilationService(
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        generation_config_service=fixture.config,
        prompt_repository=fixture.prompts,
        batch_repository=fixture.repository,
        prompt_compiler=fixture.compiler,
        image_editor=fixture.editor,
        identity_provider=identity,
        provider_model="gpt-image-2",
    )
    return fixture


def _input(source_asset_id: UUID) -> BatchHeroPromptCompilationInput:
    return BatchHeroPromptCompilationInput(
        source_asset_id=source_asset_id,
        market_id="taobao",
        model_id="gpt-image-2-5",
        style_id="precision",
        aspect_ratio="1:1",
        resolution="标准 1K",
        output_language="中文",
        custom_style="保持冷灰背景",
        modules=[
            BatchHeroModuleInput("hero-kv", 3, [{"key": "主体", "value": "居中"}]),
            BatchHeroModuleInput("hero-scene", 2, [{"key": "场景", "value": "办公桌"}]),
        ],
    )


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), (10, 20, 30)).save(output, format="PNG")
    return output.getvalue()


async def _add_project_asset(fixture, kind: str, object_id: UUID) -> UUID:
    body = _png_bytes()
    digest = __import__("hashlib").sha256(body).hexdigest()
    key = project_asset_object_key(fixture.workspace_id, fixture.project_id, object_id, "image/png")
    await fixture.storage.put(StoredObject(key, body, "image/png"))
    record = await fixture.projects.create_object(
        fixture.workspace_id,
        key,
        f"{kind}.png",
        "image/png",
        len(body),
        12,
        8,
        digest,
        object_id=object_id,
    )
    asset = await fixture.projects.create_asset(fixture.project_id, record.id, kind)
    return asset.id


@pytest.mark.asyncio
async def test_compile_batch_accepts_every_project_asset_kind_as_source() -> None:
    """回归：白底图和生成结果同样可以作为生成输入。

    前端产品素材选择器同时提供 source / base / hero 三类素材，后端曾经硬性要求
    kind == "source"，导致用户选中白底图就报「源图不属于当前项目」。三类都必须可用。
    """
    fixture = await _fixture()

    for index, kind in enumerate(("white_background", "generated"), start=1):
        asset_id = await _add_project_asset(fixture, kind, UUID(int=40 + index))

        batch = await fixture.service.compile_prompt_batch(
            fixture.project_id, _input(asset_id), f"batch-compile-{kind}"
        )

        assert batch.status == "awaiting_confirmation", kind
        assert batch.source_asset_id == asset_id


@pytest.mark.asyncio
async def test_compile_batch_still_rejects_assets_from_another_project() -> None:
    """放开素材类型不等于放开归属校验。"""
    fixture = await _fixture()
    foreign = await fixture.projects.create_project("别的项目", fixture.workspace_id)
    body = _png_bytes()
    digest = __import__("hashlib").sha256(body).hexdigest()
    object_id = UUID(int=77)
    key = project_asset_object_key(fixture.workspace_id, foreign.id, object_id, "image/png")
    await fixture.storage.put(StoredObject(key, body, "image/png"))
    record = await fixture.projects.create_object(
        fixture.workspace_id, key, "foreign.png", "image/png", len(body), 12, 8, digest,
        object_id=object_id,
    )
    asset = await fixture.projects.create_asset(foreign.id, record.id, "white_background")

    with pytest.raises(AppError) as error:
        await fixture.service.compile_prompt_batch(
            fixture.project_id, _input(asset.id), "batch-compile-foreign"
        )

    assert error.value.code == "INVALID_SOURCE_ASSET"
