from uuid import uuid4

import pytest

from backend.app.core.errors import AppError
from backend.app.suite_planning_repository import (
    InMemorySuitePlanningRepository,
    SuitePlanModuleCompilation,
    SuitePlanModuleInput,
)


def _module(key: str, position: int, count: int = 1) -> SuitePlanModuleInput:
    return SuitePlanModuleInput(
        module_key=key,
        position=position,
        requested_image_count=count,
        title=f"模块 {position}",
        module_parameters=[{"key": "重点", "value": key}],
        prompt_snapshot={"version": "builtin-suite-plan-v1"},
    )


@pytest.mark.asyncio
async def test_memory_repository_restores_latest_compiled_plan_inside_project_boundary() -> None:
    repository = InMemorySuitePlanningRepository()
    workspace_id, project_id, other_project_id = uuid4(), uuid4(), uuid4()
    plan, duplicate = await repository.create_compiling(
        workspace_id,
        project_id,
        "compile-1",
        "a" * 64,
        {"sourceAssetIds": [str(uuid4()), str(uuid4())]},
        [_module("suite-hero", 1, 2), _module("suite-benefit", 2, 3)],
    )

    await repository.mark_awaiting_confirmation(
        plan.id,
        workspace_id,
        {
            "suite-hero": SuitePlanModuleCompilation(
                "首屏文案", "首屏画面", "首屏实时提示词", {"visibleFacts": ["黑色产品"]}
            ),
            "suite-benefit": SuitePlanModuleCompilation(
                "卖点文案", "卖点画面", "卖点实时提示词", {"unconfirmedItems": ["材质"]}
            ),
        },
    )

    detail = await repository.get_latest(project_id, workspace_id)
    assert duplicate is False
    assert detail is not None
    assert detail.plan.id == plan.id
    assert detail.plan.status == "awaiting_confirmation"
    assert [(item.module_key, item.position, item.requested_image_count) for item in detail.modules] == [
        ("suite-hero", 1, 2),
        ("suite-benefit", 2, 3),
    ]
    assert detail.modules[0].current_task_prompt == "首屏实时提示词"
    assert await repository.get_plan_detail(plan.id, workspace_id, other_project_id) is None
    assert await repository.get_plan_detail(plan.id, uuid4(), project_id) is None


@pytest.mark.asyncio
async def test_memory_repository_replays_compile_idempotently_and_rejects_changed_payload() -> None:
    repository = InMemorySuitePlanningRepository()
    workspace_id, project_id = uuid4(), uuid4()
    created, _ = await repository.create_compiling(
        workspace_id, project_id, "same-key", "b" * 64, {}, [_module("suite-hero", 1)]
    )

    replay, duplicate = await repository.create_compiling(
        workspace_id, project_id, "same-key", "b" * 64, {}, [_module("suite-hero", 1)]
    )

    assert duplicate is True
    assert replay.id == created.id
    with pytest.raises(AppError) as conflict:
        await repository.create_compiling(
            workspace_id, project_id, "same-key", "c" * 64, {}, [_module("suite-hero", 1)]
        )
    assert conflict.value.code == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_memory_repository_edits_only_target_module_and_rejects_stale_revision() -> None:
    repository = InMemorySuitePlanningRepository()
    workspace_id, project_id = uuid4(), uuid4()
    plan, _ = await repository.create_compiling(
        workspace_id,
        project_id,
        "compile-edit",
        "d" * 64,
        {},
        [_module("suite-hero", 1), _module("suite-scene", 2)],
    )
    await repository.mark_awaiting_confirmation(
        plan.id,
        workspace_id,
        {
            key: SuitePlanModuleCompilation(key, key, f"prompt-{key}", {})
            for key in ("suite-hero", "suite-scene")
        },
    )
    before = await repository.get_plan_detail(plan.id, workspace_id, project_id)
    assert before is not None
    target = before.modules[1]

    updated = await repository.update_module(
        plan.id,
        target.id,
        workspace_id,
        project_id,
        expected_plan_revision=before.plan.revision,
        expected_module_revision=target.revision,
        copy_summary="只修改场景文案",
        visual_direction="新的使用场景",
        current_task_prompt="新的场景提示词",
        requested_image_count=4,
        module_parameters=[{"key": "环境", "value": "书房"}],
    )

    assert updated.plan.revision == before.plan.revision + 1
    assert updated.modules[0] == before.modules[0]
    assert updated.modules[1].copy_summary == "只修改场景文案"
    assert updated.modules[1].revision == target.revision + 1
    with pytest.raises(AppError) as conflict:
        await repository.update_module(
            plan.id,
            target.id,
            workspace_id,
            project_id,
            expected_plan_revision=before.plan.revision,
            expected_module_revision=target.revision,
            copy_summary="旧页面覆盖",
        )
    assert conflict.value.code == "SUITE_PLAN_REVISION_CONFLICT"
    assert conflict.value.status_code == 409


@pytest.mark.asyncio
async def test_memory_repository_reorders_then_freezes_confirmed_plan_idempotently() -> None:
    repository = InMemorySuitePlanningRepository()
    workspace_id, project_id = uuid4(), uuid4()
    plan, _ = await repository.create_compiling(
        workspace_id,
        project_id,
        "compile-confirm",
        "e" * 64,
        {},
        [_module("suite-hero", 1), _module("suite-benefit", 2), _module("suite-scene", 3)],
    )
    await repository.mark_awaiting_confirmation(
        plan.id,
        workspace_id,
        {
            key: SuitePlanModuleCompilation(key, key, f"prompt-{key}", {})
            for key in ("suite-hero", "suite-benefit", "suite-scene")
        },
    )
    detail = await repository.get_plan_detail(plan.id, workspace_id, project_id)
    assert detail is not None
    reordered = await repository.reorder_modules(
        plan.id,
        workspace_id,
        project_id,
        expected_plan_revision=detail.plan.revision,
        ordered_module_ids=[detail.modules[2].id, detail.modules[0].id, detail.modules[1].id],
    )
    batch_id = uuid4()

    confirmed, duplicate = await repository.mark_confirmed(
        plan.id,
        workspace_id,
        project_id,
        expected_plan_revision=reordered.plan.revision,
        idempotency_key="confirm-1",
        fingerprint="f" * 64,
        confirmed_snapshot={"frozen": True},
        generation_batch_id=batch_id,
    )
    replay, replayed = await repository.mark_confirmed(
        plan.id,
        workspace_id,
        project_id,
        expected_plan_revision=reordered.plan.revision,
        idempotency_key="confirm-1",
        fingerprint="f" * 64,
        confirmed_snapshot={"frozen": True},
        generation_batch_id=batch_id,
    )

    assert [item.module_key for item in reordered.modules] == [
        "suite-scene",
        "suite-hero",
        "suite-benefit",
    ]
    assert confirmed.status == "confirmed"
    assert confirmed.generation_batch_id == batch_id
    assert duplicate is False
    assert replayed is True
    assert replay.id == confirmed.id
    with pytest.raises(AppError) as frozen:
        await repository.reorder_modules(
            plan.id,
            workspace_id,
            project_id,
            expected_plan_revision=confirmed.revision,
            ordered_module_ids=[item.id for item in reordered.modules],
        )
    assert frozen.value.code == "SUITE_PLAN_NOT_EDITABLE"
