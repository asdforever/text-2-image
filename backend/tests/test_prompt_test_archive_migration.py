from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "c4d5e6f7a8b9_add_prompt_test_request_snapshot.py"


def test_prompt_test_request_snapshot_migration_is_linear_and_reversible() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "c4d5e6f7a8b9"' in source
    assert 'down_revision = "b2c3d4e5f6a7"' in source
    assert "ADD COLUMN IF NOT EXISTS request_snapshot jsonb" in source
    assert "DROP COLUMN IF EXISTS request_snapshot" in source


def test_readiness_revision_matches_current_migration_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(config).get_heads() == [EXPECTED_ALEMBIC_HEAD]
