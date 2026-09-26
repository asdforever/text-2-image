from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).resolve().parents[2]
REVISION = "f2a3b4c5d6e7"
MIGRATION = ROOT / "alembic" / "versions" / "f2a3b4c5d6e7_add_image_editing_and_product_library.py"


def test_image_editing_migration_is_reversible_and_kept_in_the_upgrade_chain() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    source = MIGRATION.read_text(encoding="utf-8")

    ancestors = {
        ancestor.revision
        for ancestor in script.iterate_revisions(EXPECTED_ALEMBIC_HEAD, "base")
    }
    assert REVISION in ancestors
    assert 'revision = "f2a3b4c5d6e7"' in source
    assert 'down_revision = "e1f2a3b4c5d6"' in source
    for table in (
        "image_edit_sessions",
        "image_edit_operations",
        "image_ocr_results",
        "image_edit_tasks",
        "image_edit_attempts",
        "image_edit_versions",
        "product_libraries",
        "products",
        "product_versions",
    ):
        assert f"CREATE TABLE project_workbench.{table}" in source
        assert f"DROP TABLE IF EXISTS project_workbench.{table}" in source


def test_image_editing_migration_keeps_uniqueness_and_status_constraints() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    for constraint in (
        "uq_image_edit_operations_ordinal",
        "uq_image_edit_attempts_number",
        "uq_image_edit_versions_number",
        "uq_product_versions_number",
        "product_libraries_type_check",
        "product_versions_type_check",
    ):
        assert constraint in source
