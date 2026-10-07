from io import BytesIO
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from backend.app.application.batch_generation_confirmation_service import (
    BatchGenerationConfirmationService,
)
from backend.app.application.batch_generation_worker import BatchGenerationWorker
from backend.app.application.hero_generation_ports import ImageEditResult
from backend.app.application.project_asset_service import ProjectAssetService
from backend.app.core.errors import AppError
from backend.app.batch_generation_repository import ConfirmedGenerationModuleInput
from backend.app.project_storage import project_asset_object_key
from backend.app.storage import StoredObject
from backend.tests.test_batch_generation_compile_service import _fixture, _input


class SuccessEditor:
    def __init__(self) -> None:
        self.requests = []

    def describe_request(self, request):
        return {
            "model": "gpt-image-2",
            "size": "1024x1024",
            "n": 1,
            "promptSha256": "a" * 64,
            "prompt": "不得存储的原始提示词",
        }

    async def edit(self, request):
        self.requests.append(request)
        return ImageEditResult(_png_bytes(), "image/png", self.describe_request(request))


class MultiImageEditor(SuccessEditor):
    supports_multiple_source_images = True


class FailingEditor(SuccessEditor):
    async def edit(self, request):
        self.requests.append(request)
        raise AppError("IMAGE_PROVIDER_FAILED", "图片 Provider 请求失败", 502)


class TimeoutEditor(SuccessEditor):
    async def edit(self, request):
        self.requests.append(request)
        raise AppError("IMAGE_PROVIDER_TIMEOUT", "image provider timed out", 504)


class ConcurrentEditor(SuccessEditor):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0

    async def edit(self, request):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return await super().edit(request)
        finally:
            self.active -= 1


class CancellingEditor(SuccessEditor):
    def __init__(self, repository, batch_id, workspace_id) -> None:
        super().__init__()
        self.repository = repository
        self.batch_id = batch_id
        self.workspace_id = workspace_id

    async def edit(self, request):
        self.requests.append(request)
        await self.repository.cancel_batch(self.batch_id, self.workspace_id)
        return ImageEditResult(_png_bytes(), "image/png", self.describe_request(request))


@pytest.mark.asyncio
async def test_unexpected_slot_read_error_does_not_interrupt_siblings(monkeypatch):
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    request = type(request)(**{**request.__dict__, "modules": [request.modules[0]]})
    batch = await fixture.service.compile_prompt_batch(fixture.project_id, request, "compile")
    confirmation = BatchGenerationConfirmationService(fixture.repository, fixture.service.identity_provider)
    await confirmation.confirm_batch(fixture.project_id, batch.id, await _compiled_prompts(fixture, batch), "confirm")
    original = fixture.repository.get_slot_execution
    failed_once = False

    async def read(slot_id):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("temporary slot read failure")
        return await original(slot_id)

    monkeypatch.setattr(fixture.repository, "get_slot_execution", read)
    editor = ConcurrentEditor()
    worker = BatchGenerationWorker(
        repository=fixture.repository, project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(fixture.projects, fixture.storage, fixture.service.identity_provider),
        image_editor=editor, worker_id="test-worker", concurrency=1,
    )
    assert await worker.run_once(limit=3) == 2
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert detail.progress.succeeded == 2
    # 未发送的槽位保留租约，由下一轮租约恢复安全地重新排队。
    assert detail.progress.leased == 1
    assert editor.max_active == 1
    assert await fixture.repository.recover_expired_leases(datetime.now(timezone.utc) + timedelta(seconds=61)) == 1
    assert await worker.run_once(limit=1) == 1
    recovered = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert recovered.progress.succeeded == 3


@pytest.mark.asyncio
async def test_once_mode_surfaces_unexpected_slot_errors_after_siblings_finish(monkeypatch):
    from types import SimpleNamespace

    async def claim(*args, **kwargs):
        return [SimpleNamespace(id=1, lease_token="first"), SimpleNamespace(id=2, lease_token="second")]

    finished = []
    async def execute(slot_id, lease_token):
        if slot_id == 1:
            raise OSError("slot database unavailable")
        await asyncio.sleep(.001)
        finished.append(slot_id)
        return True

    worker = BatchGenerationWorker(
        repository=SimpleNamespace(claim_queued_slots=claim), project_repository=None,
        project_storage=None, project_asset_service=None, image_editor=None, worker_id="test-worker",
    )
    monkeypatch.setattr(worker, "_execute_slot", execute)
    with pytest.raises(OSError, match="slot database unavailable"):
        await worker.run_once(limit=2, raise_on_error=True)
    assert finished == [2]


@pytest.mark.asyncio
async def test_worker_executes_one_slot_and_persists_a_generated_asset() -> None:
    fixture = await _fixture()
    batch = await fixture.service.compile_prompt_batch(
        fixture.project_id, _input(fixture.source_asset_id), "compile"
    )
    confirmation = BatchGenerationConfirmationService(
        fixture.repository, fixture.service.identity_provider
    )
    await confirmation.confirm_batch(
        fixture.project_id, batch.id, await _compiled_prompts(fixture, batch), "confirm"
    )
    editor = SuccessEditor()
    worker = BatchGenerationWorker(
        repository=fixture.repository,
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(
            fixture.projects, fixture.storage, fixture.service.identity_provider
        ),
        image_editor=editor,
        worker_id="test-worker",
    )

    completed = await worker.run_once(limit=1)
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)

    assert completed == 1
    assert len(editor.requests) == 1
    assert detail is not None
    succeeded = [slot for slot in detail.slots if slot.status == "succeeded"]
    assert len(succeeded) == 1
    asset = await fixture.projects.get_asset(succeeded[0].generated_asset_id, fixture.workspace_id)
    assert asset is not None
    assert asset.kind == "generated"
    assert asset.generation_snapshot_id == succeeded[0].id
    attempts = await fixture.repository.list_attempts(succeeded[0].id, fixture.workspace_id)
    assert attempts[-1].status == "succeeded"
    assert attempts[-1].provider_request_summary == {
        "model": "gpt-image-2", "size": "1024x1024", "n": 1, "promptSha256": "a" * 64,
        "sourceImageSha256s": [
            __import__("hashlib").sha256(editor.requests[0].image_bytes).hexdigest()
        ],
    }


@pytest.mark.asyncio
async def test_worker_marks_only_the_failing_slot_and_keeps_other_slots_queued() -> None:
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    request = type(request)(**{**request.__dict__, "modules": [request.modules[0]]})
    batch = await fixture.service.compile_prompt_batch(fixture.project_id, request, "compile")
    confirmation = BatchGenerationConfirmationService(
        fixture.repository, fixture.service.identity_provider
    )
    await confirmation.confirm_batch(fixture.project_id, batch.id, await _compiled_prompts(fixture, batch), "confirm")
    worker = BatchGenerationWorker(
        repository=fixture.repository,
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(
            fixture.projects, fixture.storage, fixture.service.identity_provider
        ),
        image_editor=FailingEditor(),
        worker_id="test-worker",
    )

    completed = await worker.run_once(limit=1)
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)

    assert completed == 0
    assert detail is not None
    assert detail.progress.failed == 1
    assert detail.progress.queued == 2


@pytest.mark.asyncio
async def test_worker_keeps_gateway_timeout_as_uncertain_for_manual_reconciliation() -> None:
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    request = type(request)(**{**request.__dict__, "modules": [request.modules[0]]})
    batch = await fixture.service.compile_prompt_batch(fixture.project_id, request, "timeout-uncertain")
    confirmation = BatchGenerationConfirmationService(
        fixture.repository, fixture.service.identity_provider
    )
    await confirmation.confirm_batch(fixture.project_id, batch.id, await _compiled_prompts(fixture, batch), "confirm-timeout-uncertain")
    worker = BatchGenerationWorker(
        repository=fixture.repository,
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(fixture.projects, fixture.storage, fixture.service.identity_provider),
        image_editor=TimeoutEditor(),
        worker_id="test-worker",
    )

    completed = await worker.run_once(limit=1)
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)

    assert completed == 0
    assert detail is not None
    assert detail.progress.needs_retry == 1
    assert detail.progress.failed == 0
    assert detail.slots[0].error_code == "PROVIDER_DISPATCH_UNKNOWN"


@pytest.mark.asyncio
async def test_worker_respects_the_configured_slot_concurrency() -> None:
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    request = type(request)(**{**request.__dict__, "modules": [request.modules[0]]})
    batch = await fixture.service.compile_prompt_batch(fixture.project_id, request, "compile")
    confirmation = BatchGenerationConfirmationService(
        fixture.repository, fixture.service.identity_provider
    )
    await confirmation.confirm_batch(fixture.project_id, batch.id, await _compiled_prompts(fixture, batch), "confirm")
    editor = ConcurrentEditor()
    worker = BatchGenerationWorker(
        repository=fixture.repository,
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(
            fixture.projects, fixture.storage, fixture.service.identity_provider
        ),
        image_editor=editor,
        worker_id="test-worker",
        concurrency=1,
    )

    completed = await worker.run_once(limit=3)

    assert completed == 3
    assert editor.max_active == 1


@pytest.mark.asyncio
async def test_worker_discards_provider_result_when_cancellation_arrives_during_dispatch() -> None:
    fixture = await _fixture()
    request = _input(fixture.source_asset_id)
    request = type(request)(**{**request.__dict__, "modules": [request.modules[0]]})
    batch = await fixture.service.compile_prompt_batch(fixture.project_id, request, "compile")
    confirmation = BatchGenerationConfirmationService(
        fixture.repository, fixture.service.identity_provider
    )
    await confirmation.confirm_batch(fixture.project_id, batch.id, await _compiled_prompts(fixture, batch), "confirm")
    worker = BatchGenerationWorker(
        repository=fixture.repository,
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(
            fixture.projects, fixture.storage, fixture.service.identity_provider
        ),
        image_editor=CancellingEditor(fixture.repository, batch.id, fixture.workspace_id),
        worker_id="test-worker",
    )

    completed = await worker.run_once(limit=1)
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assets = await fixture.projects.list_assets(fixture.project_id, fixture.workspace_id)

    assert completed == 0
    assert detail is not None
    assert detail.progress.cancelled == 3
    assert [asset.kind for asset in assets] == ["source"]


@pytest.mark.asyncio
async def test_suite_worker_uses_all_ordered_source_images_and_records_hashes() -> None:
    fixture, batch, first_object, second_hash = await _suite_worker_fixture()
    editor = MultiImageEditor()
    worker = BatchGenerationWorker(
        repository=fixture.repository,
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(
            fixture.projects, fixture.storage, fixture.service.identity_provider
        ),
        image_editor=editor,
        worker_id="suite-worker",
    )

    assert await worker.run_once(limit=1) == 1
    assert len(editor.requests) == 1
    ordered = editor.requests[0].ordered_image_inputs()
    assert [item.image_filename for item in ordered] == ["product.png", "second.png"]
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert detail is not None
    attempts = await fixture.repository.list_attempts(detail.slots[0].id, fixture.workspace_id)
    assert attempts[-1].provider_request_summary["sourceImageSha256s"] == [
        first_object.sha256,
        second_hash,
    ]


@pytest.mark.asyncio
async def test_suite_worker_rejects_provider_without_multiple_source_capability() -> None:
    fixture, batch, _first_object, _second_hash = await _suite_worker_fixture()
    editor = SuccessEditor()
    worker = BatchGenerationWorker(
        repository=fixture.repository,
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(
            fixture.projects, fixture.storage, fixture.service.identity_provider
        ),
        image_editor=editor,
        worker_id="suite-worker",
    )

    assert await worker.run_once(limit=1) == 0
    assert editor.requests == []
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert detail is not None
    assert detail.slots[0].error_code == "IMAGE_PROVIDER_MULTI_SOURCE_UNSUPPORTED"


@pytest.mark.asyncio
async def test_suite_worker_rejects_source_hash_mismatch_before_provider_call() -> None:
    fixture, batch, _first_object, _second_hash = await _suite_worker_fixture()
    fixture.repository._batches[batch.id].snapshot["sourceAssets"][0]["sha256"] = "0" * 64
    editor = MultiImageEditor()
    worker = BatchGenerationWorker(
        repository=fixture.repository,
        project_repository=fixture.projects,
        project_storage=fixture.storage,
        project_asset_service=ProjectAssetService(
            fixture.projects, fixture.storage, fixture.service.identity_provider
        ),
        image_editor=editor,
        worker_id="suite-worker",
    )

    assert await worker.run_once(limit=1) == 0
    assert editor.requests == []
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert detail is not None
    assert detail.slots[0].error_code == "INVALID_SOURCE_ASSET"


async def _suite_worker_fixture(model_connection=None):
    fixture = await _fixture()
    first_asset = await fixture.projects.get_asset(fixture.source_asset_id, fixture.workspace_id)
    assert first_asset is not None
    first_object = await fixture.projects.get_object(first_asset.object_id, fixture.workspace_id)
    assert first_object is not None
    second_bytes = _png_bytes((30, 50, 70))
    second_hash = __import__("hashlib").sha256(second_bytes).hexdigest()
    second_object_id = __import__("uuid").uuid4()
    second_key = project_asset_object_key(
        fixture.workspace_id, fixture.project_id, second_object_id, "image/png"
    )
    await fixture.storage.put(StoredObject(second_key, second_bytes, "image/png"))
    second_object = await fixture.projects.create_object(
        fixture.workspace_id, second_key, "second.png", "image/png",
        len(second_bytes), 16, 16, second_hash, object_id=second_object_id,
    )
    second_asset = await fixture.projects.create_asset(
        fixture.project_id, second_object.id, "source"
    )
    plan_id = __import__("uuid").uuid4()
    batch, _ = await fixture.repository.create_confirmed_from_plan(
        fixture.workspace_id,
        fixture.project_id,
        plan_id,
        fixture.source_asset_id,
        "suite-confirm",
        "f" * 64,
        {
            "sourceAssets": [
                {
                    "assetId": str(first_asset.id), "objectId": str(first_object.id),
                    "filename": first_object.original_filename, "mediaType": first_object.media_type,
                    "sha256": first_object.sha256,
                },
                {
                    "assetId": str(second_asset.id), "objectId": str(second_object.id),
                    "filename": second_object.original_filename, "mediaType": second_object.media_type,
                    "sha256": second_hash,
                },
            ],
            "selection": {"aspectRatio": "1:1", "resolution": "标准 1K", **({"modelConnection": model_connection} if model_connection else {})},
        },
        [
            ConfirmedGenerationModuleInput(
                "suite-hero", 1, 1, {}, "编译提示词", {}, "确认提示词",
                "最终提示词", "e" * 64,
            )
        ],
    )
    return fixture, batch, first_object, second_hash


def _png_bytes(color=(100, 120, 140)) -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16), color).save(output, format="PNG")
    return output.getvalue()


async def _compiled_prompts(fixture, batch):
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    return {task.module_key: task.compiled_task_prompt for task in detail.module_tasks}
