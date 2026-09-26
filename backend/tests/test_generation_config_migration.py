from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).parents[2]
REVISION = "a7b8c9d0e1f2"
MIGRATION = ROOT / "alembic" / "versions" / "a7b8c9d0e1f2_add_generation_config_domain.py"


def test_generation_config_migration_is_an_ancestor_of_the_current_head() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    revision = script.get_revision(REVISION)

    assert revision is not None
    assert revision.down_revision == "f6a7b8c9d0e1"
    assert script.get_revision(EXPECTED_ALEMBIC_HEAD) is not None
    assert REVISION in {item.revision for item in script.walk_revisions()}


def test_generation_config_migration_creates_only_the_configuration_domain() -> None:
    source = " ".join(MIGRATION.read_text(encoding="utf-8").split())

    assert "CREATE SCHEMA IF NOT EXISTS generation_config" in source
    for table in ("config_versions", "config_drafts"):
        assert f"CREATE TABLE generation_config.{table}" in source
        assert f"DROP TABLE IF EXISTS generation_config.{table}" in source
    assert "REFERENCES suite_workbench.workspaces(id)" in source
    assert "uq_config_versions_workspace_version" in source
    assert "config_versions_workspace_version_idx" in source
    assert "project_workbench.projects" not in source
    assert "prompt_library.prompt_templates" not in source


def test_generation_config_migration_has_offline_upgrade_sql() -> None:
    output = StringIO()
    config = Config(ROOT / "alembic.ini", output_buffer=output)
    config.set_main_option(
        "sqlalchemy.url", "postgresql+asyncpg://user:password@localhost/test"
    )

    command.upgrade(config, REVISION, sql=True)

    sql = output.getvalue()
    assert "CREATE SCHEMA IF NOT EXISTS generation_config" in sql
    assert "CREATE TABLE generation_config.config_versions" in sql
    assert "CREATE TABLE generation_config.config_drafts" in sql
