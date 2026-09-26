from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).parents[2]
REVISION = "d0e1f2a3b4c5"


def test_suite_planning_migration_remains_an_ancestor_of_current_head() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    revision = script.get_revision(REVISION)

    assert revision is not None
    assert revision.down_revision == "c9d0e1f2a3b4"
    assert script.get_heads() == [EXPECTED_ALEMBIC_HEAD]
    ancestors = {
        ancestor.revision
        for ancestor in script.iterate_revisions(EXPECTED_ALEMBIC_HEAD, "base")
    }
    assert REVISION in ancestors


def test_suite_planning_offline_upgrade_creates_plans_and_extends_batches() -> None:
    output = StringIO()
    config = Config(ROOT / "alembic.ini", output_buffer=output)
    config.set_main_option(
        "sqlalchemy.url", "postgresql+asyncpg://user:password@localhost/test"
    )

    command.upgrade(config, REVISION, sql=True)

    sql = " ".join(output.getvalue().split())
    assert "CREATE TABLE project_workbench.suite_plans" in sql
    assert "CREATE TABLE project_workbench.suite_plan_modules" in sql
    assert "ADD COLUMN kind varchar(20) NOT NULL DEFAULT 'hero'" in sql
    assert "ADD COLUMN source_plan_id uuid" in sql
    assert "ADD COLUMN position integer" in sql
    assert "UPDATE project_workbench.generation_module_tasks" in sql
    assert "uq_generation_module_tasks_batch_position" in sql
