import asyncio
from uuid import UUID

import pytest
from sqlalchemy import text

from backend.app.application.product_library_service import ProductLibraryService
from backend.app.application.product_library_service import SqlAlchemyProductLibraryService
from backend.app.application.project_archive_service import (
    ProjectArchiveBackfillService,
    ProjectArchiveCoordinator,
)
from backend.app.core.config import get_settings
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.db import create_engine, create_session_factory
from backend.app.project_repository import (
    InMemoryProjectRepository,
    ProjectAssetRecord,
    ProjectRecord,
)


def test_memory_project_archive_coordinator_is_idempotent_across_lifecycle() -> None:
    async def run() -> None:
        workspace_id = UUID(int=811)
        project = ProjectRecord(UUID(int=812), workspace_id, "键盘项目")
        asset = ProjectAssetRecord(UUID(int=813), project.id, UUID(int=814), "source")
        library_service = ProductLibraryService(
            LocalSingleUserIdentityProvider(
                IdentityContext(UUID(int=1), workspace_id, "owner")
            )
        )
        coordinator = ProjectArchiveCoordinator(library_service)

        first = await coordinator.ensure_project_archive(project)
        replay = await coordinator.ensure_project_archive(project)
        first_link = await coordinator.link_project_asset(project, asset)
        replay_link = await coordinator.link_project_asset(project, asset)

        assert first.id == replay.id
        assert first_link.id == replay_link.id
        assert [
            item.project_asset_id
            for item in await library_service.list_product_asset_links(first.id)
        ] == [asset.id]

        assert await coordinator.unlink_project_asset(project.id, asset.id) is True
        assert await library_service.list_product_asset_links(first.id) == []
        archived = await coordinator.archive_project_archive(project.id)
        assert archived is not None
        assert archived.archived_at is not None

    asyncio.run(run())


@pytest.mark.asyncio
async def test_project_archive_coordinator_delegates_output_archive() -> None:
    class ArchiveRecorder:
        async def archive_project_output(self, **payload):
            return payload

    coordinator = ProjectArchiveCoordinator(ArchiveRecorder())

    result = await coordinator.archive_project_output(project_id=UUID(int=1), product_type="detail")

    assert result == {"project_id": UUID(int=1), "product_type": "detail"}


@pytest.mark.asyncio
async def test_sql_project_archive_coordinator_reuses_project_product() -> None:
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 PostgreSQL，跳过数据库契约测试")

    engine = create_engine(settings.database_url)
    workspace_id = settings.local_workspace_id
    project = ProjectRecord(UUID(int=821), workspace_id, "SQL 项目档案")
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=1), workspace_id, "owner")
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = create_session_factory(connection)
            async with sessions() as session, session.begin():
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.projects(id, workspace_id, name) "
                        "VALUES (:id, :workspace, :name)"
                    ),
                    {"id": project.id, "workspace": workspace_id, "name": project.name},
                )
            coordinator = ProjectArchiveCoordinator(
                SqlAlchemyProductLibraryService(sessions, identity)
            )

            first = await coordinator.ensure_project_archive(project)
            replay = await coordinator.ensure_project_archive(project)
            archived = await coordinator.archive_project_archive(project.id)

            assert first.id == replay.id
            assert archived is not None
            assert archived.archived_at is not None
            await transaction.rollback()
    finally:
        await engine.dispose()


def test_project_archive_backfill_is_paged_and_repeatable() -> None:
    async def run() -> None:
        workspace_id = UUID(int=831)
        identity = LocalSingleUserIdentityProvider(
            IdentityContext(UUID(int=1), workspace_id, "owner")
        )
        repository = InMemoryProjectRepository()
        active = await repository.create_project("历史活动项目", workspace_id)
        archived = await repository.create_project("历史归档项目", workspace_id)
        active_object = await repository.create_object(
            workspace_id, "history/active.png", "active.png", "image/png", 1, 1, 1, "8" * 64
        )
        archived_object = await repository.create_object(
            workspace_id, "history/archived.png", "archived.png", "image/png", 1, 1, 1, "9" * 64
        )
        await repository.create_asset(active.id, active_object.id, "source")
        await repository.create_asset(archived.id, archived_object.id, "source")
        await repository.archive_project(archived.id, workspace_id)

        product_library = ProductLibraryService(identity)
        coordinator = ProjectArchiveCoordinator(product_library)
        backfill = ProjectArchiveBackfillService(repository, coordinator, identity)

        first = await backfill.backfill_workspace(page_size=1)
        second = await backfill.backfill_workspace(page_size=1)

        assert first.scanned == 2
        assert first.created == 2
        assert first.reused == 0
        assert first.linked == 2
        assert first.failed == 0
        assert second.scanned == 2
        assert second.created == 0
        assert second.reused == 2
        assert second.linked == 0
        assert second.failed == 0
        assert len(product_library.products) == 2

    asyncio.run(run())
