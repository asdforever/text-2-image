from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).parents[2]
REVISION = "c9d0e1f2a3b4"
MIGRATION = ROOT / "alembic" / "versions" / "c9d0e1f2a3b4_add_batch_generation_orchestration.py"


def test_batch_generation_migration_is_the_current_head() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    revision = script.get_revision(REVISION)

    assert revision is not None
    assert revision.down_revision == "b8c9d0e1f2a3"
    assert script.get_heads() == [EXPECTED_ALEMBIC_HEAD]
    assert script.get_revision("d0e1f2a3b4c5") is not None


def test_batch_generation_migration_creates_four_new_tables_without_rewriting_3a() -> None:
    source = " ".join(MIGRATION.read_text(encoding="utf-8").split())

    for table in (
        "generation_batches",
        "generation_module_tasks",
        "generation_image_slots",
        "generation_slot_attempts",
    ):
        assert f"CREATE TABLE project_workbench.{table}" in source
        assert f"DROP TABLE IF EXISTS project_workbench.{table}" in source
    assert "hero_generation_tasks" not in source
    assert "generation_module_tasks_requested_image_count_check" in source
    assert "generation_image_slots_status_check" in source
    assert "generation_slot_attempts_status_check" in source
    assert "generation_image_slots_queue_idx" in source


def test_batch_generation_migration_has_offline_upgrade_sql() -> None:
    output = StringIO()
    config = Config(ROOT / "alembic.ini", output_buffer=output)
    config.set_main_option(
        "sqlalchemy.url", "postgresql+asyncpg://user:password@localhost/test"
    )

    command.upgrade(config, REVISION, sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE project_workbench.generation_batches" in sql
    assert "CREATE TABLE project_workbench.generation_image_slots" in sql
