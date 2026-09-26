from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).parents[2]
REVISION = "b8c9d0e1f2a3"
MIGRATION = ROOT / "alembic" / "versions" / "b8c9d0e1f2a3_add_hero_generation_tasks.py"


def test_hero_generation_migration_is_an_ancestor_of_the_current_head() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    revision = script.get_revision(REVISION)

    assert revision is not None
    assert revision.down_revision == "a7b8c9d0e1f2"
    assert script.get_revision(EXPECTED_ALEMBIC_HEAD) is not None
    assert REVISION in {item.revision for item in script.walk_revisions()}


def test_hero_generation_migration_creates_task_constraints_and_foreign_keys() -> None:
    source = " ".join(MIGRATION.read_text(encoding="utf-8").split())

    assert "CREATE TABLE project_workbench.hero_generation_tasks" in source
    assert "uq_hero_generation_compile_idempotency" in source
    assert "uq_hero_generation_confirm_idempotency" in source
    assert "hero_generation_tasks_status_check" in source
    assert "REFERENCES project_workbench.projects(id)" in source
    assert "REFERENCES project_workbench.project_assets(id)" in source
    assert "DROP TABLE IF EXISTS project_workbench.hero_generation_tasks" in source


def test_hero_generation_migration_has_offline_upgrade_sql() -> None:
    output = StringIO()
    config = Config(ROOT / "alembic.ini", output_buffer=output)
    config.set_main_option(
        "sqlalchemy.url", "postgresql+asyncpg://user:password@localhost/test"
    )

    command.upgrade(config, REVISION, sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE project_workbench.hero_generation_tasks" in sql
    assert "hero_generation_tasks_project_status_idx" in sql
