from pathlib import Path

from backend.app.core.config import Settings


ROOT = Path(__file__).resolve().parents[2]


def test_default_env_file_is_project_root_and_cwd_independent(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    env_file = Path(Settings.model_config["env_file"])

    assert env_file.is_absolute()
    assert env_file == ROOT / ".env"


def test_settings_build_database_url_from_existing_pg_environment(monkeypatch) -> None:
    for key in ("DATABASE_URL", "PG_HOST", "PG_PORT", "PG_DATABASE", "PG_USER", "PG_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PG_HOST", "db.example.test")
    monkeypatch.setenv("PG_PORT", "5432")
    monkeypatch.setenv("PG_DATABASE", "picagent_dev")
    monkeypatch.setenv("PG_USER", "app_user")
    monkeypatch.setenv("PG_PASSWORD", "secret")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+asyncpg://app_user:secret@db.example.test:5432/picagent_dev"
