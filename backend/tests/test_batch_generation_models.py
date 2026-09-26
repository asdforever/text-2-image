from sqlalchemy import CheckConstraint, UniqueConstraint, inspect

from backend.app.models.base import Base
from backend.app.models.batch_generation import (
    GenerationBatch,
    GenerationImageSlot,
    GenerationModuleTask,
    GenerationSlotAttempt,
)


def _check_names(model: type) -> set[str | None]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_batch_generation_models_keep_snapshots_and_slot_boundaries() -> None:
    batch_columns = {column.name for column in inspect(GenerationBatch).columns}
    module_columns = {column.name for column in inspect(GenerationModuleTask).columns}
    slot_columns = {column.name for column in inspect(GenerationImageSlot).columns}
    attempt_columns = {column.name for column in inspect(GenerationSlotAttempt).columns}

    assert {
        "id",
        "workspace_id",
        "project_id",
        "source_asset_id",
        "kind",
        "source_plan_id",
        "status",
        "compile_idempotency_key",
        "compile_fingerprint",
        "confirm_idempotency_key",
        "confirm_fingerprint",
        "snapshot",
    } <= batch_columns
    assert {
        "id",
        "batch_id",
        "module_key",
        "position",
        "requested_image_count",
        "snapshot",
        "compiled_task_prompt",
        "compiler_output",
        "confirmed_task_prompt",
        "final_prompt",
        "final_prompt_sha256",
    } <= module_columns
    assert {
        "id",
        "batch_id",
        "module_task_id",
        "ordinal",
        "status",
        "generated_asset_id",
        "lease_token",
        "lease_expires_at",
        "provider_idempotency_key",
    } <= slot_columns
    assert {
        "id",
        "slot_id",
        "attempt_no",
        "status",
        "lease_token",
        "provider_request_summary",
    } <= attempt_columns

    assert "generation_batches_status_check" in _check_names(GenerationBatch)
    assert "generation_batches_kind_check" in _check_names(GenerationBatch)
    assert "generation_module_tasks_requested_image_count_check" in _check_names(
        GenerationModuleTask
    )
    assert "generation_image_slots_status_check" in _check_names(GenerationImageSlot)
    assert "generation_image_slots_ordinal_check" in _check_names(GenerationImageSlot)
    assert "generation_slot_attempts_status_check" in _check_names(GenerationSlotAttempt)
    assert Base.metadata.tables["project_workbench.generation_batches"] is GenerationBatch.__table__


def test_batch_generation_models_define_idempotency_and_execution_indexes() -> None:
    batch_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in GenerationBatch.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    module_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in GenerationModuleTask.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    slot_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in GenerationImageSlot.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    attempt_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in GenerationSlotAttempt.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    slot_indexes = {tuple(index.columns.keys()) for index in GenerationImageSlot.__table__.indexes}

    assert ("workspace_id", "compile_idempotency_key") in batch_uniques
    assert ("workspace_id", "confirm_idempotency_key") in batch_uniques
    assert ("source_plan_id",) in batch_uniques
    assert ("batch_id", "module_key") in module_uniques
    assert ("batch_id", "position") in module_uniques
    assert ("module_task_id", "ordinal") in slot_uniques
    assert ("slot_id", "attempt_no") in attempt_uniques
    assert ("status", "lease_expires_at", "created_at") in slot_indexes
