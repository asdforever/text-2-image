from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD
from backend.app.models.prompt import PromptTemplate


ROOT = Path(__file__).resolve().parents[2]
REVISION = "03a4b5c6d7e8"
MIGRATION = ROOT / "alembic" / "versions" / "03a4b5c6d7e8_restore_prompt_template_stage.py"


def test_prompt_template_stage_is_backed_by_the_current_database_head() -> None:
    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    source = MIGRATION.read_text(encoding="utf-8")

    assert "stage" in PromptTemplate.__table__.columns
    ancestors = {ancestor.revision for ancestor in script.iterate_revisions(EXPECTED_ALEMBIC_HEAD, "base")}
    assert REVISION in ancestors
    assert 'down_revision = "f2a3b4c5d6e7"' in source
    assert "ADD COLUMN IF NOT EXISTS stage" in source
    assert "UPDATE prompt_library.prompt_templates" in source
    assert "ALTER COLUMN stage SET NOT NULL" in source


def test_prompt_template_stage_migration_is_reversible() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "DROP COLUMN IF EXISTS stage" in source
