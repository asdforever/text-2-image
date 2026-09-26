from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "c3d4e5f6a7b8_add_local_workspace_scope.py"


def test_workspace_migration_is_attached_to_current_migration_graph() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    revision = script.get_revision("c3d4e5f6a7b8")

    assert revision is not None
    assert revision.down_revision == "b7c2e4d91a6f"
    assert script.get_heads() == [EXPECTED_ALEMBIC_HEAD]
    assert revision.revision in {item.revision for item in script.walk_revisions()}


def test_workspace_migration_creates_scope_and_backfills_existing_suites() -> None:
    source = " ".join(MIGRATION.read_text(encoding="utf-8").split())

    assert "CREATE TABLE IF NOT EXISTS suite_workbench.workspaces" in source
    assert "ALTER TABLE suite_workbench.suites ADD COLUMN IF NOT EXISTS workspace_id uuid" in source
    assert "UPDATE suite_workbench.suites SET workspace_id" in source
    assert "ALTER TABLE suite_workbench.suites ALTER COLUMN workspace_id SET NOT NULL" in source
    assert "REFERENCES suite_workbench.workspaces(id)" in source
    assert "DROP COLUMN IF EXISTS workspace_id" in source
    assert "DROP TABLE IF EXISTS suite_workbench.workspaces" in source


def test_workspace_migration_uses_the_local_identity_default() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "22222222-2222-4222-8222-222222222222" in source
