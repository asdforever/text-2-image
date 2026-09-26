from sqlalchemy import CheckConstraint, UniqueConstraint, inspect

from backend.app.models.base import Base
from backend.app.models.workbench import (
    WorkbenchLayout,
    WorkbenchReference,
    WorkbenchTask,
    WorkbenchTaskVersion,
)


def _checks(model: type) -> set[str | None]:
    return {item.name for item in model.__table__.constraints if isinstance(item, CheckConstraint)}


def _uniques(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(item.columns.keys())
        for item in model.__table__.constraints
        if isinstance(item, UniqueConstraint)
    }


def test_workbench_models_keep_scope_revision_and_version_boundaries() -> None:
    task_columns = {column.name for column in inspect(WorkbenchTask).columns}
    version_columns = {column.name for column in inspect(WorkbenchTaskVersion).columns}
    layout_columns = {column.name for column in inspect(WorkbenchLayout).columns}
    reference_columns = {column.name for column in inspect(WorkbenchReference).columns}

    assert {"id", "workspace_id", "project_id", "plan_snapshot_id", "plan_item_id", "title", "purpose", "prompt_draft", "prompt_revision", "generation_params", "status", "archived_at", "current_version_id", "final_version_id"} <= task_columns
    assert {"id", "task_id", "batch_id", "slot_id", "version_number", "object_key", "preview_url", "prompt_snapshot", "context_snapshot", "is_current", "is_final"} <= version_columns
    assert {"id", "workspace_id", "project_id", "layout_version", "viewport", "nodes", "groups"} <= layout_columns
    assert {"id", "workspace_id", "project_id", "target_type", "target_id", "resource_type", "resource_id", "resource_version", "source_snapshot", "archived_at"} <= reference_columns

    assert "workbench_tasks_status_check" in _checks(WorkbenchTask)
    assert "workbench_tasks_revision_check" in _checks(WorkbenchTask)
    assert "workbench_layouts_version_check" in _checks(WorkbenchLayout)
    assert ("project_id", "target_type", "target_id", "resource_type", "resource_id", "resource_version") in _uniques(WorkbenchReference)
    assert Base.metadata.tables["project_workbench.workbench_tasks"] is WorkbenchTask.__table__
