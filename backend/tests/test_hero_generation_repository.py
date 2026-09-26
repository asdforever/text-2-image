from uuid import uuid4

import pytest

from backend.app.core.errors import AppError
from backend.app.hero_generation_repository import InMemoryHeroGenerationRepository


@pytest.mark.asyncio
async def test_compile_idempotency_reuses_the_same_task_and_rejects_new_payload() -> None:
    repository = InMemoryHeroGenerationRepository()
    workspace_id = uuid4()
    project_id = uuid4()
    source_asset_id = uuid4()

    first, duplicate = await repository.create_compiling(
        workspace_id,
        project_id,
        source_asset_id,
        "compile-key",
        "request-fingerprint",
        {"configVersion": 2},
    )
    replay, replay_duplicate = await repository.create_compiling(
        workspace_id,
        project_id,
        source_asset_id,
        "compile-key",
        "request-fingerprint",
        {"configVersion": 2},
    )

    assert duplicate is False
    assert replay_duplicate is True
    assert replay.id == first.id
    with pytest.raises(AppError, match="different request") as conflict:
        await repository.create_compiling(
            workspace_id,
            project_id,
            source_asset_id,
            "compile-key",
            "other-fingerprint",
            {"configVersion": 3},
        )
    assert conflict.value.code == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_confirmation_transitions_once_and_preserves_both_prompt_versions() -> None:
    repository = InMemoryHeroGenerationRepository()
    workspace_id = uuid4()
    task, _ = await repository.create_compiling(
        workspace_id, uuid4(), uuid4(), "compile-key", "compile-fingerprint", {}
    )
    awaiting = await repository.mark_awaiting_confirmation(
        task.id,
        workspace_id,
        compiled_task_prompt="原始实时任务提示词",
        compiler_output={"visibleFacts": ["黑色"]},
    )

    running, duplicate = await repository.begin_confirmation(
        awaiting.id,
        workspace_id,
        "confirm-key",
        "confirm-fingerprint",
        confirmed_task_prompt="用户编辑后的实时任务提示词",
        final_prompt="固定平台卡\n固定风格卡\n用户编辑后的实时任务提示词",
        final_prompt_sha256="a" * 64,
        provider_request={"size": "1024x1024", "n": 1},
    )
    replay, replay_duplicate = await repository.begin_confirmation(
        awaiting.id,
        workspace_id,
        "confirm-key",
        "confirm-fingerprint",
        confirmed_task_prompt="用户编辑后的实时任务提示词",
        final_prompt="固定平台卡\n固定风格卡\n用户编辑后的实时任务提示词",
        final_prompt_sha256="a" * 64,
        provider_request={"size": "1024x1024", "n": 1},
    )

    assert duplicate is False
    assert running.status == "generating"
    assert running.compiled_task_prompt == "原始实时任务提示词"
    assert running.confirmed_task_prompt == "用户编辑后的实时任务提示词"
    assert replay_duplicate is True
    assert replay.id == running.id

    completed = await repository.complete(running.id, workspace_id, uuid4())
    assert completed.status == "succeeded"
    assert completed.generated_asset_id is not None


@pytest.mark.asyncio
async def test_tasks_are_workspace_scoped_and_invalid_transitions_are_rejected() -> None:
    repository = InMemoryHeroGenerationRepository()
    workspace_id = uuid4()
    task, _ = await repository.create_compiling(
        workspace_id, uuid4(), uuid4(), "compile-key", "fingerprint", {}
    )

    assert await repository.get_task(task.id, uuid4()) is None
    with pytest.raises(AppError) as invalid:
        await repository.begin_confirmation(
            task.id,
            workspace_id,
            "confirm-key",
            "fingerprint",
            confirmed_task_prompt="尚未完成编译",
            final_prompt="尚未完成编译",
            final_prompt_sha256="b" * 64,
            provider_request={"n": 1},
        )
    assert invalid.value.code == "HERO_GENERATION_INVALID_STATE"
