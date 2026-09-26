from uuid import uuid4

from sqlalchemy import UniqueConstraint, inspect

from backend.app.models.base import Base
from backend.app.models.generation_config import ConfigDraft, ConfigVersion


def test_generation_config_models_define_versioned_workspace_documents() -> None:
    version = ConfigVersion(
        workspace_id=uuid4(),
        version_no=1,
        content={"version": 1},
        content_sha256="a" * 64,
    )
    draft = ConfigDraft(
        workspace_id=version.workspace_id,
        base_version_no=1,
        content={"version": 1},
    )

    assert version.version_no == 1
    assert draft.base_version_no == 1
    assert Base.metadata.tables["generation_config.config_versions"] is ConfigVersion.__table__


def test_generation_config_models_expose_workspace_unique_constraints_and_indexes() -> None:
    version_columns = {column.name for column in inspect(ConfigVersion).columns}
    draft_columns = {column.name for column in inspect(ConfigDraft).columns}
    version_uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in ConfigVersion.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert {"id", "workspace_id", "version_no", "content", "content_sha256", "created_at"} <= version_columns
    assert {"workspace_id", "base_version_no", "content", "updated_at"} <= draft_columns
    assert ("workspace_id", "version_no") in version_uniques
    assert any(index.columns.keys() == ["workspace_id"] for index in ConfigVersion.__table__.indexes)
