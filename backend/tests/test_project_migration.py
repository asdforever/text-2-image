from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).parents[2]
REVISION = "f6a7b8c9d0e1"
MIGRATION = ROOT / "alembic" / "versions" / "f6a7b8c9d0e1_add_project_asset_domain.py"


def test_project_asset_migration_is_an_ancestor_of_the_current_head() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    revision = script.get_revision(REVISION)

    assert revision is not None
    assert revision.down_revision == "e5f6a7b8c9d0"
    assert script.get_revision(EXPECTED_ALEMBIC_HEAD) is not None
    assert REVISION in {item.revision for item in script.walk_revisions()}


def test_project_asset_migration_creates_only_the_project_domain() -> None:
    source = " ".join(MIGRATION.read_text(encoding="utf-8").split())

    assert "CREATE SCHEMA IF NOT EXISTS project_workbench" in source
    for table in ("projects", "asset_objects", "project_assets", "project_asset_selections"):
        assert f"CREATE TABLE project_workbench.{table}" in source
        assert f"DROP TABLE IF EXISTS project_workbench.{table}" in source
    assert "suite_workbench.suites" not in source
    assert "prompt_library.assets" not in source
    assert "project_assets_kind_check" in source
    assert "project_asset_selections_role_check" in source


def test_project_asset_migration_has_offline_upgrade_and_downgrade_sql() -> None:
    upgrade_output = StringIO()
    upgrade_config = Config(ROOT / "alembic.ini", output_buffer=upgrade_output)
    upgrade_config.set_main_option(
        "sqlalchemy.url", "postgresql+asyncpg://user:password@localhost/test"
    )
    command.upgrade(upgrade_config, REVISION, sql=True)

    upgrade_sql = upgrade_output.getvalue()
    assert "CREATE SCHEMA IF NOT EXISTS project_workbench" in upgrade_sql
    assert "CREATE TABLE project_workbench.project_assets" in upgrade_sql

    downgrade_output = StringIO()
    downgrade_config = Config(ROOT / "alembic.ini", output_buffer=downgrade_output)
    downgrade_config.set_main_option(
        "sqlalchemy.url", "postgresql+asyncpg://user:password@localhost/test"
    )
    command.downgrade(downgrade_config, f"{REVISION}:e5f6a7b8c9d0", sql=True)

    downgrade_sql = downgrade_output.getvalue()
    assert "DROP TABLE IF EXISTS project_workbench.project_asset_selections" in downgrade_sql
    assert "DROP TABLE IF EXISTS project_workbench.projects" in downgrade_sql
