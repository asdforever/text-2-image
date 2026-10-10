import pytest

from backend.app.application.batch_generation_confirmation_service import (
    BatchGenerationConfirmationService,
)
from backend.app.core.errors import AppError
from backend.tests.test_batch_generation_compile_service import RecordingV2Compiler, _fixture, _input


@pytest.mark.asyncio
async def test_confirm_batch_freezes_module_prompts_and_creates_five_slots() -> None:
    fixture = await _fixture()
    batch = await fixture.service.compile_prompt_batch(
        fixture.project_id, _input(fixture.source_asset_id), "compile"
    )
    service = BatchGenerationConfirmationService(fixture.repository, fixture.service.identity_provider)

    compiled_detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    prompts = {task.module_key: task.compiled_task_prompt for task in compiled_detail.module_tasks}
    confirmed = await service.confirm_batch(fixture.project_id, batch.id, prompts, "confirm")
    detail = await fixture.repository.get_batch_detail(confirmed.id, fixture.workspace_id)

    assert confirmed.status == "queued"
    assert detail is not None
    assert len(detail.slots) == 5
    assert detail.progress.queued == 5
    assert detail.module_tasks[0].final_prompt is not None
    assert detail.module_tasks[0].confirmed_task_prompt == prompts["hero-kv"]


@pytest.mark.asyncio
async def test_duplicate_batch_confirmation_does_not_create_extra_slots() -> None:
    fixture = await _fixture()
    batch = await fixture.service.compile_prompt_batch(
        fixture.project_id, _input(fixture.source_asset_id), "compile"
    )
    service = BatchGenerationConfirmationService(fixture.repository, fixture.service.identity_provider)
    compiled_detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    edits = {task.module_key: task.compiled_task_prompt for task in compiled_detail.module_tasks}

    first = await service.confirm_batch(fixture.project_id, batch.id, edits, "confirm")
    replay = await service.confirm_batch(fixture.project_id, batch.id, edits, "confirm")
    detail = await fixture.repository.get_batch_detail(first.id, fixture.workspace_id)

    assert replay.id == first.id
    assert detail is not None
    assert len(detail.slots) == 5


@pytest.mark.asyncio
async def test_incomplete_module_edits_leave_batch_awaiting_confirmation() -> None:
    fixture = await _fixture()
    batch = await fixture.service.compile_prompt_batch(
        fixture.project_id, _input(fixture.source_asset_id), "compile"
    )
    service = BatchGenerationConfirmationService(fixture.repository, fixture.service.identity_provider)

    with pytest.raises(AppError) as raised:
        await service.confirm_batch(
            fixture.project_id, batch.id, {"hero-kv": "只提交了一个模块"}, "confirm"
        )
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)

    assert raised.value.code == "BATCH_GENERATION_INVALID_INPUT"
    assert detail is not None
    assert detail.batch.status == "awaiting_confirmation"
    assert detail.slots == []


@pytest.mark.asyncio
async def test_v2_batch_confirmation_preserves_manual_prompt_and_original_compile() -> None:
    fixture = await _fixture(planner_version="v2")
    fixture.compiler = RecordingV2Compiler()
    fixture.service.prompt_compiler = fixture.compiler
    batch = await fixture.service.compile_prompt_batch(
        fixture.project_id, _input(fixture.source_asset_id), "compile-v2"
    )
    detail = await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)
    assert detail is not None
    compiled = {task.module_key: task.compiled_task_prompt for task in detail.module_tasks}
    service = BatchGenerationConfirmationService(fixture.repository, fixture.service.identity_provider)

    changed = dict(compiled)
    changed["hero-kv"] += " 右侧增加留白"

    confirmed = await service.confirm_batch(
        fixture.project_id, batch.id, changed, "confirm-v2"
    )
    confirmed_detail = await fixture.repository.get_batch_detail(
        confirmed.id, fixture.workspace_id
    )
    assert confirmed_detail is not None
    for task in confirmed_detail.module_tasks:
        assert task.final_prompt == task.confirmed_task_prompt == changed[task.module_key]
        assert task.compiled_task_prompt == compiled[task.module_key]
