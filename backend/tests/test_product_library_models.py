from sqlalchemy import CheckConstraint, UniqueConstraint, inspect

from backend.app.models.base import Base
from backend.app.models.asset import TestProduct as PromptTestProduct, TestRun as PromptTestRun
from backend.app.models.product_library import (
    Product,
    ProductAssetLink,
    ProductLibrary,
    ProductVersion,
)


def _checks(model: type) -> set[str | None]:
    return {item.name for item in model.__table__.constraints if isinstance(item, CheckConstraint)}


def _uniques(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(item.columns.keys())
        for item in model.__table__.constraints
        if isinstance(item, UniqueConstraint)
    }


def test_production_product_library_models_keep_type_and_provenance_boundaries() -> None:
    library_columns = {column.name for column in inspect(ProductLibrary).columns}
    product_columns = {column.name for column in inspect(Product).columns}
    version_columns = {column.name for column in inspect(ProductVersion).columns}

    assert {"id", "workspace_id", "name", "library_type", "archived_at"} <= library_columns
    assert {"id", "library_id", "workspace_id", "name", "product_type", "archived_at"} <= product_columns
    assert {"id", "product_id", "version_number", "source_snapshot", "object_key", "is_current"} <= version_columns
    assert "product_libraries_type_check" in _checks(ProductLibrary)
    assert "products_type_check" in _checks(Product)
    assert "product_versions_type_check" in _checks(ProductVersion)
    assert ("product_id", "version_number") in _uniques(ProductVersion)
    assert Base.metadata.tables["project_workbench.product_libraries"] is ProductLibrary.__table__


def test_project_product_and_asset_link_models_enforce_archive_identity() -> None:
    product_indexes = {item.name: item for item in Product.__table__.indexes}
    link_columns = {column.name for column in inspect(ProductAssetLink).columns}
    link_uniques = _uniques(ProductAssetLink)
    link_indexes = {item.name for item in ProductAssetLink.__table__.indexes}

    active_project = product_indexes["uq_products_workspace_project_active"]
    assert active_project.unique is True
    assert tuple(column.name for column in active_project.columns) == (
        "workspace_id",
        "project_id",
    )
    assert active_project.dialect_options["postgresql"]["where"] is not None

    assert {
        "id",
        "workspace_id",
        "project_id",
        "product_id",
        "project_asset_id",
        "created_at",
    } <= link_columns
    assert ("product_id", "project_asset_id") in link_uniques
    assert "product_asset_links_project_idx" in link_indexes
    assert Base.metadata.tables["project_workbench.product_asset_links"] is ProductAssetLink.__table__


def test_prompt_test_product_has_one_result_per_test_run() -> None:
    test_run_index = next(
        item for item in PromptTestProduct.__table__.indexes
        if item.name == "uq_prompt_products_test_run"
    )

    assert test_run_index.unique is True
    assert tuple(column.name for column in test_run_index.columns) == ("test_run_id",)
    assert test_run_index.dialect_options["postgresql"]["where"] is not None
    assert "request_snapshot" in {column.name for column in inspect(PromptTestRun).columns}
