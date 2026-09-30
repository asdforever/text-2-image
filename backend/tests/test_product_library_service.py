from uuid import UUID

import pytest
from sqlalchemy import text

from backend.app.application.product_library_service import (
    ProductLibraryService,
    SqlAlchemyProductLibraryService,
)
from backend.app.core.config import get_settings
from backend.app.db import create_engine, create_session_factory
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.core.errors import AppError


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)


class _ProductListSession:
    def __init__(self):
        self.queries: list[str] = []

    async def execute(self, statement, _params=None):
        query = str(statement)
        self.queries.append(query)
        if "FROM project_workbench.products" in query:
            return _Rows([
                {"id": UUID(int=801), "library_id": UUID(int=800), "workspace_id": UUID(int=1), "name": "产品 A", "project_id": UUID(int=811), "archived_at": None},
                {"id": UUID(int=802), "library_id": UUID(int=800), "workspace_id": UUID(int=1), "name": "产品 B", "project_id": UUID(int=812), "archived_at": None},
            ])
        if "FROM project_workbench.product_versions" in query:
            return _Rows([
                {"id": UUID(int=821), "product_id": UUID(int=801), "product_type": "hero", "source_snapshot": {}, "preview_url": "/hero", "status": "published", "created_at": None},
                {"id": UUID(int=822), "product_id": UUID(int=802), "product_type": "detail", "source_snapshot": {}, "preview_url": "/detail", "status": "published", "created_at": None},
            ])
        raise AssertionError(f"unexpected query: {query}")


class _ProductListSessions:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        outer = self

        class Context:
            async def __aenter__(self):
                return outer.session

            async def __aexit__(self, *_args):
                return False

        return Context()


@pytest.mark.asyncio
async def test_production_library_crud_and_publish_is_idempotent():
    workspace_id = UUID(int=71)
    service = ProductLibraryService(LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")))
    library = await service.create_library("正式成品")
    product = await service.create_product(library.id, "键盘", project_id=UUID(int=9))
    listed = await service.list_products(library.id)
    assert listed[0].id == product.id
    await service.archive_product(product.id)
    assert await service.list_products(library.id) == []
    published = await service.publish_version(library.id, product.id, {"id": "version-1", "status": "succeeded", "previewUrl": "/api/image-editor/versions/version-1/preview"}, product_type="hero", idempotency_key="pub-1")
    replay = await service.publish_version(library.id, product.id, {"id": "version-1", "status": "succeeded", "previewUrl": "/api/image-editor/versions/version-1/preview"}, product_type="hero", idempotency_key="pub-1")
    assert published.id == replay.id
    assert published.preview_url == "/api/image-editor/versions/version-1/preview"
    assert len(await service.list_versions(product.id, product_type="hero", status="published")) == 1
    await service.archive_version(product.id, published.id)
    assert await service.list_versions(product.id, status="published") == []


@pytest.mark.asyncio
async def test_sql_product_list_preloads_versions_in_one_query() -> None:
    session = _ProductListSession()
    service = SqlAlchemyProductLibraryService(
        _ProductListSessions(session),
        LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), UUID(int=1), "owner")),
    )

    products = await service.list_products(UUID(int=800))

    assert [item.name for item in products] == ["产品 A", "产品 B"]
    assert [item.versions[0].id for item in products] == [UUID(int=821), UUID(int=822)]
    assert sum("FROM project_workbench.product_versions" in query for query in session.queries) == 1


@pytest.mark.asyncio
async def test_published_version_preview_url_is_read_only_source_snapshot() -> None:
    workspace_id = UUID(int=73)
    service = ProductLibraryService(LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")))
    library = await service.create_library("预览验证")
    product = await service.create_product(library.id, "键盘")
    source = {"id": "version-2", "status": "succeeded", "previewUrl": "/api/projects/p/versions/v/preview"}

    published = await service.publish_version(library.id, product.id, source, product_type="detail")
    source["previewUrl"] = "/api/other/changed"

    assert published.preview_url == "/api/projects/p/versions/v/preview"
    assert published.source_snapshot["previewUrl"] == "/api/projects/p/versions/v/preview"

@pytest.mark.asyncio
async def test_production_library_can_be_archived_and_hidden_from_default_list():
    workspace_id = UUID(int=72)
    service = ProductLibraryService(LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")))
    library = await service.create_library("待归档")
    assert len(await service.list_libraries()) == 1
    archived = await service.archive_library(library.id)
    assert archived.archived_at is not None
    assert await service.list_libraries() == []


@pytest.mark.asyncio
async def test_project_output_archive_groups_generated_versions_under_one_project_product():
    workspace_id = UUID(int=74)
    service = ProductLibraryService(LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")))
    project_id = UUID(int=75)
    white_asset_id = UUID(int=76)
    hero_asset_id = UUID(int=77)

    white = await service.archive_project_output(
        project_id=project_id,
        project_name="鼠标项目",
        product_type="white_background",
        source_version_id=white_asset_id,
        preview_url=f"/api/projects/{project_id}/assets/{white_asset_id}/preview",
        source_snapshot={"assetId": str(white_asset_id)},
    )
    replay = await service.archive_project_output(
        project_id=project_id,
        project_name="鼠标项目",
        product_type="white_background",
        source_version_id=white_asset_id,
        preview_url=f"/api/projects/{project_id}/assets/{white_asset_id}/preview",
        source_snapshot={"assetId": str(white_asset_id)},
    )
    hero = await service.archive_project_output(
        project_id=project_id,
        project_name="鼠标项目",
        product_type="hero",
        source_version_id=hero_asset_id,
        preview_url=f"/api/projects/{project_id}/assets/{hero_asset_id}/preview",
        source_snapshot={"assetId": str(hero_asset_id)},
    )

    library = next(item for item in await service.list_libraries() if item.name == "项目成品库")
    products = await service.list_products(library.id)
    assert len(products) == 1
    assert products[0].project_id == project_id
    assert white.id == replay.id
    assert [item.product_type for item in products[0].versions] == ["white_background", "hero"]
    assert hero.preview_url.endswith(f"/{hero_asset_id}/preview")


@pytest.mark.asyncio
async def test_sql_product_library_supports_the_complete_route_contract():
    """正式库使用数据库时，全部成品库路由仍应可用。"""
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 PostgreSQL，跳过数据库契约测试")

    engine = create_engine(settings.database_url)
    workspace_id = settings.local_workspace_id
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=1), workspace_id, "owner")
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = create_session_factory(connection)
            service = SqlAlchemyProductLibraryService(sessions, identity)
            library = await service.create_library("SQL 成品库契约")
            product = await service.create_product(library.id, "SQL 产品")
            version = await service.publish_version(
                library.id,
                product.id,
                {
                    "id": str(UUID(int=742)),
                    "status": "succeeded",
                    "previewUrl": "/api/projects/sql/versions/742/preview",
                },
                product_type="hero",
                idempotency_key="sql-product-library-contract",
            )

            assert (await service.get_product(product.id)).id == product.id
            assert [item.id for item in await service.list_versions(product.id)] == [version.id]
            assert (await service.get_version(product.id, version.id)).id == version.id
            assert (await service.archive_version(product.id, version.id)).status == "archived"
            assert (await service.archive_product(product.id)).archived_at is not None
            assert (await service.archive_library(library.id)).archived_at is not None
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_product_asset_links_are_idempotent_and_workspace_scoped():
    """同一项目资产只能关联一次，其他工作区不能读取或删除该关联。"""
    settings = get_settings()
    if not settings.database_url:
        pytest.skip("未配置 PostgreSQL，跳过数据库契约测试")

    engine = create_engine(settings.database_url)
    workspace_id = settings.local_workspace_id
    project_id = UUID(int=751)
    object_id = UUID(int=752)
    asset_id = UUID(int=753)
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
                        "VALUES (:id, :workspace, '关联测试项目')"
                    ),
                    {"id": project_id, "workspace": workspace_id},
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.asset_objects("
                        "id, workspace_id, storage_key, original_filename, media_type, "
                        "byte_size, width, height, sha256) VALUES ("
                        ":id, :workspace, :key, 'source.png', 'image/png', 1, 1, 1, :sha)"
                    ),
                    {
                        "id": object_id,
                        "workspace": workspace_id,
                        "key": f"tests/product-links/{object_id}.png",
                        "sha": "7" * 64,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.project_assets("
                        "id, project_id, object_id, kind) VALUES (:id, :project, :object, 'source')"
                    ),
                    {"id": asset_id, "project": project_id, "object": object_id},
                )

            service = SqlAlchemyProductLibraryService(sessions, identity)
            library = await service.create_library("SQL 资产关联契约")
            product = await service.create_product(
                library.id, "关联测试项目", project_id=project_id
            )

            first = await service.link_project_asset(product.id, project_id, asset_id)
            replay = await service.link_project_asset(product.id, project_id, asset_id)
            assert first.id == replay.id
            assert [item.project_asset_id for item in await service.list_product_asset_links(product.id)] == [asset_id]

            other_workspace = SqlAlchemyProductLibraryService(
                sessions,
                LocalSingleUserIdentityProvider(
                    IdentityContext(UUID(int=2), UUID(int=999), "owner")
                ),
            )
            with pytest.raises(AppError) as error:
                await other_workspace.list_product_asset_links(product.id)
            assert error.value.status_code == 404

            assert await service.unlink_project_asset(product.id, asset_id) is True
            assert await service.list_product_asset_links(product.id) == []
            await transaction.rollback()
    finally:
        await engine.dispose()
