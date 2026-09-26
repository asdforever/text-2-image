from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).resolve().parents[2]
REVISION = "e1f2a3b4c5d6"
MIGRATION = ROOT / "alembic" / "versions" / "e1f2a3b4c5d6_add_workbench_state.py"


def test_workbench_migration_is_current_head_and_has_reversible_tables() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    source = MIGRATION.read_text(encoding="utf-8")

    ancestors = {
        ancestor.revision
        for ancestor in script.iterate_revisions(EXPECTED_ALEMBIC_HEAD, "base")
    }
    assert REVISION in ancestors
    assert 'revision = "e1f2a3b4c5d6"' in source
    assert 'down_revision = "d0e1f2a3b4c5"' in source
    for table in ("workbench_tasks", "workbench_task_versions", "workbench_layouts", "workbench_references"):
        assert f"CREATE TABLE project_workbench.{table}" in source
        assert f"DROP TABLE IF EXISTS project_workbench.{table}" in source


def test_workbench_migration_keeps_task_version_and_layout_constraints() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "uq_workbench_tasks_plan_item" in source
    assert "uq_workbench_task_versions_number" in source
    assert "uq_workbench_layouts_project" in source
    assert "uq_workbench_references_resource" in source
