from datetime import datetime, timedelta, timezone
import asyncio
from uuid import uuid4

import pytest

from backend.app.batch_generation_repository import (
    ConfirmedGenerationModuleInput,
    GenerationModuleCompilation,
    GenerationModuleConfirmation,
    GenerationModuleInput,
    InMemoryBatchGenerationRepository,
)
from backend.app.core.errors import AppError


def _module_inputs() -> list[GenerationModuleInput]:
    return [
        GenerationModuleInput("hero-kv", 3, {"module": "hero-kv"}),
        GenerationModuleInput("scene", 2, {"module": "scene"}),
    ]


async def _awaiting_batch(repository: InMemoryBatchGenerationRepository, workspace_id):
    batch, _ = await repository.create_compiling(
        workspace_id,
        uuid4(),
        uuid4(),
        "compile-key",
        "a" * 64,
        {"configVersion": 2},
        _module_inputs(),
    )
    return await repository.mark_awaiting_confirmation(
        batch.id,
        workspace_id,
        {
            "hero-kv": GenerationModuleCompilation("主图 KV 任务", {"visibleFacts": ["黑色"]}),
            "scene": GenerationModuleCompilation("使用场景任务", {"visibleFacts": ["桌面"]}),
        },
    )


async def _queued_suite_batch(repository, workspace_id, *, first_count=2, second_count=2):
    project_id, source_asset_id, plan_id = uuid4(), uuid4(), uuid4()
    module_inputs = [
        ConfirmedGenerationModuleInput(
            "suite-first", 1, first_count, {}, "编译一", {}, "确认一", "最终一", "1" * 64
        ),
        ConfirmedGenerationModuleInput(
            "suite-second", 2, second_count, {}, "编译二", {}, "确认二", "最终二", "2" * 64
        ),
    ]
    batch, _ = await repository.create_confirmed_from_plan(
        workspace_id, project_id, plan_id, source_asset_id,
        f"confirm-{plan_id}", "3" * 64,
        {"sourceAssets": [{"assetId": str(source_asset_id)}]}, module_inputs,
    )
    return batch


@pytest.mark.asyncio
async def test_batch_creation_is_workspace_scoped_and_compile_idempotent() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    project_id = uuid4()
    source_asset_id = uuid4()

    first, duplicate = await repository.create_compiling(
        workspace_id,
        project_id,
        source_asset_id,
        "compile-key",
        "a" * 64,
        {"configVersion": 2},
        _module_inputs(),
    )
    replay, replay_duplicate = await repository.create_compiling(
        workspace_id,
        project_id,
        source_asset_id,
        "compile-key",
        "a" * 64,
        {"configVersion": 2},
        _module_inputs(),
    )

    assert duplicate is False
    assert replay_duplicate is True
    assert replay.id == first.id
    assert await repository.get_batch(first.id, uuid4()) is None
    with pytest.raises(AppError) as conflict:
        await repository.create_compiling(
            workspace_id,
            project_id,
            source_asset_id,
            "compile-key",
            "b" * 64,
            {"configVersion": 3},
            _module_inputs(),
        )
    assert conflict.value.code == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_confirmation_enqueues_exact_slots_once_and_aggregates_batch_progress() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    awaiting = await _awaiting_batch(repository, workspace_id)
    confirmations = {
        "hero-kv": GenerationModuleConfirmation("用户确认的 KV", "约束卡\n用户确认的 KV", "c" * 64),
        "scene": GenerationModuleConfirmation("用户确认的场景", "约束卡\n用户确认的场景", "d" * 64),
    }

    confirmed, duplicate = await repository.confirm_and_enqueue(
        awaiting.id, workspace_id, "confirm-key", "e" * 64, confirmations
    )
    replay, replay_duplicate = await repository.confirm_and_enqueue(
        awaiting.id, workspace_id, "confirm-key", "e" * 64, confirmations
    )
    detail = await repository.get_batch_detail(confirmed.id, workspace_id)

    assert duplicate is False
    assert replay_duplicate is True
    assert replay.id == confirmed.id
    assert confirmed.status == "queued"
    assert detail is not None
    assert detail.progress.total == 5
    assert detail.progress.queued == 5
    assert detail.progress.completed == 0
    assert [slot.ordinal for slot in detail.slots if slot.module_key == "hero-kv"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_suite_claims_independent_modules_together_and_preserves_display_order() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    batch = await _queued_suite_batch(repository, workspace_id)

    first = await repository.claim_queued_slots(
        "worker", limit=4, lease_duration=timedelta(seconds=30)
    )
    assert [slot.module_key for slot in first] == ["suite-first", "suite-first", "suite-second", "suite-second"]
    for slot in first:
        await repository.mark_dispatching(slot.id, slot.lease_token)
        await repository.complete_slot(slot.id, slot.lease_token, uuid4())

    second = await repository.claim_queued_slots(
        "worker", limit=4, lease_duration=timedelta(seconds=30)
    )
    assert second == []
    detail = await repository.get_batch_detail(batch.id, workspace_id)
    assert detail is not None
    assert [task.position for task in detail.module_tasks] == [1, 2]


@pytest.mark.asyncio
async def test_retrying_previous_suite_module_does_not_block_independent_later_slots() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    await _queued_suite_batch(repository, workspace_id, first_count=1, second_count=2)
    first = (await repository.claim_queued_slots(
        "worker", limit=1, lease_duration=timedelta(seconds=30)
    ))[0]
    await repository.mark_dispatching(first.id, first.lease_token)
    await repository.fail_slot(first.id, first.lease_token, "FAILED", "失败")
    leased_later = await repository.claim_queued_slots(
        "worker", limit=1, lease_duration=timedelta(seconds=30)
    )
    assert leased_later[0].module_key == "suite-second"

    await repository.retry_slot(first.id, workspace_id)
    claimed = await repository.claim_queued_slots(
        "worker", limit=3, lease_duration=timedelta(seconds=30)
    )
    assert [slot.module_key for slot in claimed] == ["suite-first", "suite-second"]


@pytest.mark.asyncio
async def test_suite_lease_recovery_does_not_resend_unknown_dispatch() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    await _queued_suite_batch(repository, workspace_id, first_count=1, second_count=1)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = (await repository.claim_queued_slots(
        "worker-a", limit=1, lease_duration=timedelta(seconds=10), now=now
    ))[0]
    assert first.module_key == "suite-first"

    assert await repository.recover_expired_leases(now + timedelta(seconds=11)) == 1
    retried = (await repository.claim_queued_slots(
        "worker-b", limit=1, lease_duration=timedelta(seconds=10),
        now=now + timedelta(seconds=12),
    ))[0]
    assert retried.id == first.id
    await repository.mark_dispatching(
        retried.id, retried.lease_token, now + timedelta(seconds=13)
    )

    assert await repository.recover_expired_leases(now + timedelta(seconds=23)) == 1
    next_module = await repository.claim_queued_slots(
        "worker-c", limit=2, lease_duration=timedelta(seconds=10),
        now=now + timedelta(seconds=24),
    )
    assert [slot.module_key for slot in next_module] == ["suite-second"]
    attempts = await repository.list_attempts(first.id, workspace_id)
    assert [attempt.attempt_no for attempt in attempts] == [1, 2]
    assert attempts[-1].status == "needs_retry"


@pytest.mark.asyncio
async def test_leased_slots_keep_attempt_history_and_recover_only_before_dispatch() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    awaiting = await _awaiting_batch(repository, workspace_id)
    await repository.confirm_and_enqueue(
        awaiting.id,
        workspace_id,
        "confirm-key",
        "e" * 64,
        {
            "hero-kv": GenerationModuleConfirmation("KV", "约束卡\nKV", "c" * 64),
            "scene": GenerationModuleConfirmation("场景", "约束卡\n场景", "d" * 64),
        },
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    leased = await repository.claim_queued_slots(
        "worker-a", limit=1, lease_duration=timedelta(seconds=10), now=now
    )
    recovered = await repository.recover_expired_leases(now + timedelta(seconds=11))
    detail = await repository.get_batch_detail(awaiting.id, workspace_id)

    assert len(leased) == 1
    assert leased[0].status == "leased"
    assert recovered == 1
    assert detail is not None
    assert detail.progress.queued == 5
    attempts = await repository.list_attempts(leased[0].id, workspace_id)
    assert [(attempt.attempt_no, attempt.status) for attempt in attempts] == [(1, "leased")]


@pytest.mark.asyncio
async def test_dispatched_lease_recovers_as_explicit_manual_retry() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    awaiting = await _awaiting_batch(repository, workspace_id)
    await repository.confirm_and_enqueue(
        awaiting.id,
        workspace_id,
        "confirm-key",
        "e" * 64,
        {
            "hero-kv": GenerationModuleConfirmation("KV", "约束卡\nKV", "c" * 64),
            "scene": GenerationModuleConfirmation("场景", "约束卡\n场景", "d" * 64),
        },
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    leased = (await repository.claim_queued_slots(
        "worker-a", limit=1, lease_duration=timedelta(seconds=10), now=now
    ))[0]
    await repository.mark_dispatching(leased.id, leased.lease_token, now)

    recovered = await repository.recover_expired_leases(now + timedelta(seconds=11))
    detail = await repository.get_batch_detail(awaiting.id, workspace_id)

    assert recovered == 1
    assert detail is not None
    recovered_slot = next(slot for slot in detail.slots if slot.id == leased.id)
    assert recovered_slot.status == "needs_retry"
    assert detail.progress.needs_retry == 1


@pytest.mark.asyncio
async def test_concurrent_workers_do_not_claim_the_same_slot() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    awaiting = await _awaiting_batch(repository, workspace_id)
    await repository.confirm_and_enqueue(
        awaiting.id,
        workspace_id,
        "confirm-key",
        "e" * 64,
        {
            "hero-kv": GenerationModuleConfirmation("KV", "约束卡\nKV", "c" * 64),
            "scene": GenerationModuleConfirmation("场景", "约束卡\n场景", "d" * 64),
        },
    )

    first, second = await asyncio.gather(
        repository.claim_queued_slots("worker-a", limit=3, lease_duration=timedelta(seconds=30)),
        repository.claim_queued_slots("worker-b", limit=3, lease_duration=timedelta(seconds=30)),
    )

    claimed_ids = [slot.id for slot in [*first, *second]]
    assert len(claimed_ids) == 5
    assert len(set(claimed_ids)) == 5


@pytest.mark.asyncio
async def test_cancelling_a_batch_cancels_queued_slots_without_touching_attempt_history() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    awaiting = await _awaiting_batch(repository, workspace_id)
    await repository.confirm_and_enqueue(
        awaiting.id,
        workspace_id,
        "confirm-key",
        "e" * 64,
        {
            "hero-kv": GenerationModuleConfirmation("KV", "约束卡\nKV", "c" * 64),
            "scene": GenerationModuleConfirmation("场景", "约束卡\n场景", "d" * 64),
        },
    )

    cancelled = await repository.cancel_batch(awaiting.id, workspace_id)
    detail = await repository.get_batch_detail(awaiting.id, workspace_id)

    assert cancelled.status == "cancelled"
    assert detail is not None
    assert detail.progress.cancelled == 5
    assert await repository.claim_queued_slots(
        "worker", limit=5, lease_duration=timedelta(seconds=30)
    ) == []


@pytest.mark.asyncio
async def test_retry_requeues_only_a_failed_slot() -> None:
    repository = InMemoryBatchGenerationRepository()
    workspace_id = uuid4()
    awaiting = await _awaiting_batch(repository, workspace_id)
    await repository.confirm_and_enqueue(
        awaiting.id,
        workspace_id,
        "confirm-key",
        "e" * 64,
        {
            "hero-kv": GenerationModuleConfirmation("KV", "约束卡\nKV", "c" * 64),
            "scene": GenerationModuleConfirmation("场景", "约束卡\n场景", "d" * 64),
        },
    )
    leased = (await repository.claim_queued_slots(
        "worker", limit=1, lease_duration=timedelta(seconds=30)
    ))[0]
    await repository.mark_dispatching(leased.id, leased.lease_token)
    await repository.fail_slot(leased.id, leased.lease_token, "IMAGE_PROVIDER_FAILED", "图片 Provider 请求失败")

    retried = await repository.retry_slot(leased.id, workspace_id)
    detail = await repository.get_batch_detail(awaiting.id, workspace_id)

    assert retried.status == "queued"
    assert detail is not None
    assert detail.progress.queued == 5
    attempts = await repository.list_attempts(leased.id, workspace_id)
    assert [(attempt.attempt_no, attempt.status) for attempt in attempts] == [(1, "failed")]
