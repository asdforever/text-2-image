"""真实仓储验证：图片在内存存储中，数据库写入随外层事务回滚。"""
import os
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.core.config import Settings
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.db import create_engine
from backend.app.project_repository import PostgresProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage
from backend.app.application.idempotency import PostgresIdempotencyStore
from backend.app.application.project_archive_service import ProjectArchiveCoordinator
from backend.app.application.product_library_service import SqlAlchemyProductLibraryService
from backend.app.application.project_asset_service import ProjectAssetService
from backend.app.application.long_image_service import LongImageService
from backend.app.application.long_image_rendering import LongImageRecipe
from backend.tests.test_long_image_composer import png
from backend.app.application.style_harmonization_service import StyleHarmonizationService
from backend.app.application.hero_generation_ports import ImageEditResult
from backend.app.canvas_generation_repository import PostgresCanvasGenerationRepository
from backend.app.prompt_repository import MemoryPromptRepository


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("PICAGENT_LONG_IMAGE_DB_CHECK") != "1", reason="显式启用本机事务回滚验证")
async def test_real_asset_snapshot_and_archive_persist_across_service_instances():
    engine = create_engine(Settings().database_url)
    workspace_id = uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("INSERT INTO suite_workbench.workspaces(id,name) VALUES (:id,'长图回滚验证')"), {"id": workspace_id})
                sessions = async_sessionmaker(connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
                repo, storage = PostgresProjectRepository(sessions), MemoryProjectAssetStorage()
                archive = SqlAlchemyProductLibraryService(sessions, identity)
                assets = ProjectAssetService(repo, storage, identity, project_archive=ProjectArchiveCoordinator(archive))
                project = await repo.create_project("长图回滚项目", workspace_id)
                source = await assets.upload_asset(project.id, "source", png("red"), "image/png", "原图.png")
                recipe = LongImageRecipe.model_validate({"title": "回滚长图", "width": 320, "items": [{"assetId": str(source.id)}]})
                service = LongImageService(assets, archive, PostgresIdempotencyStore(sessions))
                saved = await service.save(project.id, recipe, "one")
                reopened = LongImageService(assets, SqlAlchemyProductLibraryService(sessions, identity), PostgresIdempotencyStore(sessions))
                assert (await reopened.list(project.id))[0] == saved
                assert (await reopened.save(project.id, recipe, "one"))["assetId"] == saved["assetId"]
                product = await archive.get_project_product(project.id)
                assert len(await archive.list_versions(product.id)) == 1
                assert len(await archive.list_product_asset_links(product.id)) == 2
                assert len(await repo.list_assets(project.id, workspace_id)) == 2
                store = PostgresIdempotencyStore(sessions)
                retry_scope = f"{workspace_id}:long-image:test-retry"
                assert (await store.claim(retry_scope, "retry", "a" * 64)).is_owner
                await store.fail(retry_scope, "retry", "a" * 64, response_status=503, response_body={})
                assert not (await store.claim(retry_scope, "retry", "a" * 64)).is_owner
                assert (await store.claim(retry_scope, "retry", "a" * 64, retry_failed=True)).is_owner
                assert not (await store.claim(retry_scope, "retry", "a" * 64, retry_failed=True)).is_owner
                # 真实 JSON 仓储保存风格任务；模型与图片存储均为本地假实现。
                class Editor:
                    supports_multiple_source_images = True
                    calls = 0

                    async def edit(self, request):
                        self.calls += 1
                        return ImageEditResult(png("blue"), "image/png", {})

                editor = Editor()
                prompts = MemoryPromptRepository()
                def style_service():
                    return StyleHarmonizationService(PostgresCanvasGenerationRepository(sessions), repo,
                        storage, assets, editor, archive, identity, "fake-model", prompts)
                styling = style_service()
                payload = {"assetIds": [str(source.id)], "mode": "custom", "prompt": "暖色自然光，保留文字与商品"}
                preview = await styling.preview(project.id, payload)
                confirmed = payload | {"expectedPreviewHash": preview["previewHash"]}
                job = await styling.submit(project.id, confirmed, "style-once")
                await styling.execute(project.id, job["id"])
                restored_style = style_service()
                stored_job = (await restored_style.list_jobs(project.id))[0]
                assert stored_job["status"] == "succeeded"
                assert stored_job["tasks"][0]["archiveStatus"] == "succeeded"
                assert stored_job["finalPrompt"] == preview["finalPrompt"]
                assert (await restored_style.submit(project.id, confirmed, "style-once"))["id"] == job["id"]
                await restored_style.execute(project.id, job["id"])
                assert editor.calls == 1
                assert len(await archive.list_versions(product.id)) == 2
                assert len(await repo.list_assets(project.id, workspace_id)) == 3
            finally:
                await transaction.rollback()
        async with engine.connect() as check:
            assert await check.scalar(text("SELECT count(*) FROM suite_workbench.workspaces WHERE id=:id"), {"id": workspace_id}) == 0
    finally:
        await engine.dispose()
