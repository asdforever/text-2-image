from sqlalchemy import CheckConstraint, UniqueConstraint, inspect

from backend.app.models.base import Base
from backend.app.models.hero_generation import HeroGenerationTask


def test_hero_generation_task_model_has_snapshot_and_idempotency_boundaries() -> None:
    columns = {column.name for column in inspect(HeroGenerationTask).columns}
    uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in HeroGenerationTask.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    checks = {
        constraint.name
        for constraint in HeroGenerationTask.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert {
        "id",
        "workspace_id",
        "project_id",
        "source_asset_id",
        "status",
        "compile_idempotency_key",
        "compile_fingerprint",
        "confirm_idempotency_key",
        "confirm_fingerprint",
        "snapshot",
        "compiled_task_prompt",
        "compiler_output",
        "confirmed_task_prompt",
        "final_prompt",
        "final_prompt_sha256",
        "provider_request",
        "generated_asset_id",
        "error_code",
        "error_message",
    } <= columns
    assert ("workspace_id", "compile_idempotency_key") in uniques
    assert ("workspace_id", "confirm_idempotency_key") in uniques
    assert "hero_generation_tasks_status_check" in checks
    assert Base.metadata.tables["project_workbench.hero_generation_tasks"] is HeroGenerationTask.__table__

    assert HeroGenerationTask.__table__.c.status.default.arg == "compiling_prompt"
