from uuid import uuid4

from sqlalchemy import CheckConstraint, inspect

from backend.app.models.base import Base
from backend.app.models.project import AssetObject, Project, ProjectAsset, ProjectAssetSelection


def test_project_asset_models_define_isolated_workspace_relationships() -> None:
    project = Project(name="键盘主图", workspace_id=uuid4())
    object_record = AssetObject(
        workspace_id=project.workspace_id,
        storage_key="projects/demo/source.png",
        media_type="image/png",
        byte_size=128,
        sha256="a" * 64,
    )
    asset = ProjectAsset(
        project_id=project.id,
        object_id=object_record.id,
        kind="source",
    )
    selection = ProjectAssetSelection(
        project_id=project.id,
        role="source",
        project_asset_id=asset.id,
    )

    assert selection.role == "source"
    assert Base.metadata.tables["project_workbench.projects"] is Project.__table__


def test_project_asset_models_expose_required_keys_and_constraints() -> None:
    project_columns = {column.name for column in inspect(Project).columns}
    object_columns = {column.name for column in inspect(AssetObject).columns}
    asset_columns = {column.name for column in inspect(ProjectAsset).columns}

    assert {"id", "workspace_id", "name", "status", "archived_at"} <= project_columns
    assert {
        "storage_key",
        "original_filename",
        "media_type",
        "byte_size",
        "width",
        "height",
        "sha256",
        "state",
        "cleanup_attempted_at",
    } <= object_columns
    assert {"project_id", "object_id", "kind", "source_asset_id", "generation_snapshot_id"} <= asset_columns
    assert ProjectAssetSelection.__table__.primary_key.columns.keys() == ["project_id", "role"]
    assert ProjectAsset.__table__.c.object_id.foreign_keys
    assert ProjectAsset.__table__.c.source_asset_id.foreign_keys
    assert Project.__table__.c.status.default.arg == "active"
    assert AssetObject.__table__.c.state.default.arg == "available"
    assert ProjectAsset.__table__.c.state.default.arg == "available"
    project_checks = {
        constraint.name
        for constraint in Project.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    asset_checks = {
        constraint.name
        for constraint in ProjectAsset.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert project_checks == {"projects_status_check"}
    assert asset_checks == {"project_assets_kind_check", "project_assets_state_check"}
