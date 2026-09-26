from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).parents[2]
REVISION = "b2c3d4e5f6a7"
MIGRATION = ROOT / "alembic" / "versions" / "b2c3d4e5f6a7_add_project_asset_product_archive.py"


def test_project_asset_product_archive_migration_is_linear_and_reversible() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "b2c3d4e5f6a7"' in source
    assert 'down_revision = "a1b2c3d4e5f6"' in source
    ancestors = {
        ancestor.revision
        for ancestor in script.iterate_revisions(EXPECTED_ALEMBIC_HEAD, "base")
    }
    assert REVISION in ancestors

    assert "ROW_NUMBER() OVER" in source
    assert "uq_products_workspace_project_active" in source
    assert "CREATE TABLE project_workbench.product_asset_links" in source
    assert "uq_product_asset_links_product_asset" in source
    assert "uq_prompt_products_test_run" in source

    assert "DROP TABLE IF EXISTS project_workbench.product_asset_links" in source
    assert "DROP INDEX IF EXISTS project_workbench.uq_products_workspace_project_active" in source
    assert "DROP INDEX IF EXISTS prompt_library.uq_prompt_products_test_run" in source
