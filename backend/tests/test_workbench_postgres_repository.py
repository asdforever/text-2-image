from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_postgres_workbench_repository_uses_atomic_revision_updates() -> None:
    source = (ROOT / "backend" / "app" / "workbench_repository.py").read_text(encoding="utf-8")

    assert "class PostgresWorkbenchRepository" in source
    assert "prompt_revision=:expected_revision" in source
    assert "layout_version=:expected_version" in source
    assert "async with self.sessions() as session, session.begin()" in source
    assert "to_regclass('project_workbench.workbench_tasks')" in source
