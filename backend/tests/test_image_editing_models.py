from sqlalchemy import CheckConstraint, UniqueConstraint, inspect

from backend.app.models.base import Base
from backend.app.models.image_editing import (
    ImageEditAttempt,
    ImageEditOperation,
    ImageEditSession,
    ImageEditTask,
    ImageEditVersion,
    ImageOcrResult,
)


def _checks(model: type) -> set[str | None]:
    return {item.name for item in model.__table__.constraints if isinstance(item, CheckConstraint)}


def _uniques(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(item.columns.keys())
        for item in model.__table__.constraints
        if isinstance(item, UniqueConstraint)
    }


def test_image_editing_models_keep_scope_revision_and_snapshot_boundaries() -> None:
    session_columns = {column.name for column in inspect(ImageEditSession).columns}
    operation_columns = {column.name for column in inspect(ImageEditOperation).columns}
    ocr_columns = {column.name for column in inspect(ImageOcrResult).columns}
    task_columns = {column.name for column in inspect(ImageEditTask).columns}
    attempt_columns = {column.name for column in inspect(ImageEditAttempt).columns}
    version_columns = {column.name for column in inspect(ImageEditVersion).columns}

    assert {"id", "workspace_id", "project_id", "source_version_id", "revision", "status", "operations_snapshot"} <= session_columns
    assert {"id", "session_id", "ordinal", "operation_type", "payload", "revision"} <= operation_columns
    assert {"id", "session_id", "source_version_id", "text", "regions", "provider_snapshot"} <= ocr_columns
    assert {"id", "session_id", "status", "prompt_snapshot", "config_snapshot", "revision"} <= task_columns
    assert {"id", "task_id", "attempt_number", "status", "error_message"} <= attempt_columns
    assert {"id", "task_id", "attempt_id", "version_number", "object_key", "source_snapshot", "is_current", "is_final"} <= version_columns

    assert "image_edit_sessions_revision_check" in _checks(ImageEditSession)
    assert "image_edit_operations_revision_check" in _checks(ImageEditOperation)
    assert "image_edit_tasks_revision_check" in _checks(ImageEditTask)
    assert ("session_id", "ordinal") in _uniques(ImageEditOperation)
    assert ("task_id", "attempt_number") in _uniques(ImageEditAttempt)
    assert ("task_id", "version_number") in _uniques(ImageEditVersion)
    assert Base.metadata.tables["project_workbench.image_edit_sessions"] is ImageEditSession.__table__
