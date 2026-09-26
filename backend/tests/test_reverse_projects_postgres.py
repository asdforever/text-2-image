import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "c0d1e2f3a4b5_add_reverse_projects.py"
TEST_DATABASE_URL = os.getenv("PICAGENT_MIGRATION_TEST_DATABASE_URL")


def test_reverse_migration_executes_one_statement_per_asyncpg_call(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("reverse_migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    migration.downgrade()
    assert len(statements) >= 10
    assert all(len([part for part in statement.split(";") if part.strip()]) == 1 for statement in statements)


def test_reverse_project_migration_creates_scoped_immutable_storage() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision = "b9c0d1e2f3a4"' in source
    assert "project_workbench.reverse_projects" in source
    assert "project_workbench.reverse_project_references" in source
    assert "project_workbench.reverse_versions" in source
    assert "project_workbench.reverse_bindings" in source
    assert "UNIQUE (reverse_project_id, revision)" in source
    assert "COALESCE(target_module_id, '')" in source
    assert "CHECK (target IN ('hero', 'suite'))" in source
    assert "CHECK (scope IN ('overall', 'module'))" in source


def test_reverse_projects_revision_is_the_current_migration_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from backend.app.migration_guard import EXPECTED_ALEMBIC_HEAD

    script = ScriptDirectory.from_config(Config(ROOT / "alembic.ini"))
    assert EXPECTED_ALEMBIC_HEAD == "c0d1e2f3a4b5"
    assert script.get_heads() == [EXPECTED_ALEMBIC_HEAD]


def test_app_factory_selects_postgres_reverse_repository(monkeypatch) -> None:
    import backend.app.main as main_module
    from backend.app.core.config import Settings
    from backend.app.reverse_project_repository import PostgresReverseProjectRepository

    class Engine:
        async def dispose(self):
            return None

    sessions = object()
    monkeypatch.setattr(main_module, "create_engine", lambda _url: Engine())
    monkeypatch.setattr(main_module, "create_session_factory", lambda _engine: sessions)
    app = main_module.create_app(
        settings=Settings(_env_file=None, database_url="postgresql+asyncpg://test/test")
    )
    assert isinstance(app.state.reverse_project_repository, PostgresReverseProjectRepository)
    assert app.state.reverse_project_repository.sessions is sessions


@pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="设置 PICAGENT_MIGRATION_TEST_DATABASE_URL 指向专用 PostgreSQL 测试库",
)
def test_postgres_reverse_repository_rolls_back_stale_revision() -> None:
    from backend.app.core.errors import AppError
    from backend.app.db import create_engine, create_session_factory
    from backend.app.reverse_project_repository import PostgresReverseProjectRepository

    database_name = urlsplit(TEST_DATABASE_URL or "").path.lstrip("/").lower()
    assert "test" in database_name, "只允许连接数据库名含 test 的专用测试库"

    async def run() -> None:
        engine = create_engine(TEST_DATABASE_URL or "")
        sessions = create_session_factory(engine)
        workspace_id = uuid4()
        try:
            async with sessions() as session, session.begin():
                await session.execute(
                    text(
                        "INSERT INTO suite_workbench.workspaces (id, name) "
                        "VALUES (:id, :name)"
                    ),
                    {"id": workspace_id, "name": "反推仓储契约测试"},
                )
            repository = PostgresReverseProjectRepository(sessions)
            project = await repository.create_project(workspace_id, "数据库反推", "家电")
            updated = await repository.update_project(
                workspace_id, project.id, 1, {"summary": "服务端摘要"}
            )
            assert updated.revision == 2
            with pytest.raises(AppError) as stale:
                await repository.update_project(
                    workspace_id, project.id, 1, {"summary": "不应写入"}
                )
            assert stale.value.code == "REVERSE_PROJECT_REVISION_CONFLICT"
            persisted = await repository.get_project(workspace_id, project.id)
            assert persisted is not None
            assert persisted.summary == "服务端摘要"
            assert persisted.revision == 2
        finally:
            async with sessions() as session, session.begin():
                await session.execute(
                    text("DELETE FROM suite_workbench.workspaces WHERE id=:id"),
                    {"id": workspace_id},
                )
            await engine.dispose()

    import asyncio

    asyncio.run(run())
