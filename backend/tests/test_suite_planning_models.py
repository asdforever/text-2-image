from sqlalchemy import CheckConstraint, UniqueConstraint, inspect

from backend.app.models.base import Base
from backend.app.models.suite_planning import SuitePlan, SuitePlanModule


def _check_names(model: type) -> set[str | None]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _unique_columns(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_suite_plan_model_keeps_workspace_revisions_and_frozen_snapshots() -> None:
    columns = {column.name for column in inspect(SuitePlan).columns}

    assert {
        "id",
        "workspace_id",
        "project_id",
        "status",
        "revision",
        "requested_module_count",
        "compile_idempotency_key",
        "compile_fingerprint",
        "confirm_idempotency_key",
        "confirm_fingerprint",
        "snapshot",
        "confirmed_snapshot",
        "generation_batch_id",
        "error_code",
        "error_message",
    } <= columns
    assert ("workspace_id", "compile_idempotency_key") in _unique_columns(SuitePlan)
    assert ("workspace_id", "confirm_idempotency_key") in _unique_columns(SuitePlan)
    assert "suite_plans_status_check" in _check_names(SuitePlan)
    assert "suite_plans_revision_check" in _check_names(SuitePlan)
    assert "suite_plans_module_count_check" in _check_names(SuitePlan)
    assert SuitePlan.__table__.c.status.default.arg == "compiling"
    assert Base.metadata.tables["project_workbench.suite_plans"] is SuitePlan.__table__


def test_suite_plan_module_model_enforces_order_count_and_independent_revision() -> None:
    columns = {column.name for column in inspect(SuitePlanModule).columns}

    assert {
        "id",
        "plan_id",
        "module_key",
        "position",
        "requested_image_count",
        "revision",
        "title",
        "copy_summary",
        "visual_direction",
        "module_parameters",
        "prompt_snapshot",
        "compiled_task_prompt",
        "compiler_output",
        "current_task_prompt",
    } <= columns
    assert ("plan_id", "module_key") in _unique_columns(SuitePlanModule)
    assert ("plan_id", "position") in _unique_columns(SuitePlanModule)
    assert "suite_plan_modules_position_check" in _check_names(SuitePlanModule)
    assert "suite_plan_modules_requested_image_count_check" in _check_names(SuitePlanModule)
    assert "suite_plan_modules_revision_check" in _check_names(SuitePlanModule)
    assert Base.metadata.tables["project_workbench.suite_plan_modules"] is SuitePlanModule.__table__
