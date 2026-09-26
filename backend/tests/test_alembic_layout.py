from pathlib import Path
from io import StringIO

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD


ROOT = Path(__file__).parents[2]


def test_alembic_is_root_database_migration_source() -> None:
    assert (ROOT / "alembic.ini").exists()
    assert (ROOT / "alembic" / "env.py").exists()
    versions = sorted((ROOT / "alembic" / "versions").glob("*.py"))
    assert versions
    migration_text = "\n".join(path.read_text(encoding="utf-8") for path in versions)
    assert "prompt_templates" in migration_text
    assert "prompt_versions" in migration_text
    assert "protect_prompt_version" in migration_text
    assert "pic_agent_suite_workbench" not in (ROOT / "backend" / "cli.py").read_text(encoding="utf-8")
    legacy_runner = (ROOT / "backend" / "app" / "migrations.py").read_text(
        encoding="utf-8"
    )
    assert "run_migrations" not in legacy_runner
    assert "CREATE TABLE" not in legacy_runner
    readme = (ROOT / "backend" / "README.md").read_text(encoding="utf-8")
    assert "Alembic 是唯一" in readme


def test_alembic_migration_graph_has_one_upgrade_head() -> None:
    config = Config(ROOT / "alembic.ini")
    script = ScriptDirectory.from_config(config)

    assert len(script.get_heads()) == 1
    assert script.get_heads() == [EXPECTED_ALEMBIC_HEAD]


def test_offline_upgrade_adds_generation_params_only_once() -> None:
    output = StringIO()
    config = Config(ROOT / "alembic.ini", output_buffer=output)
    config.set_main_option(
        "sqlalchemy.url", "postgresql+asyncpg://user:password@localhost/test"
    )

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue().lower()
    assert sql.count("add column generation_params") == 1


def test_application_startup_does_not_execute_database_ddl() -> None:
    source = (ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    for forbidden in ("command.upgrade", "metadata.create_all", "run_migrations"):
        assert forbidden not in source
