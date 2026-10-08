import asyncio
from io import BytesIO
from uuid import UUID

from PIL import Image

from backend.app.application.project_asset_service import ProjectAssetService
from backend.app.application.product_library_service import ProductLibraryService
from backend.app.application.project_archive_service import ProjectArchiveCoordinator
from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.core.errors import AppError
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage


def _png(color: str = "red") -> bytes:
    image = Image.new("RGB", (16, 9), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_project_asset_service_uploads_source_and_white_background_version() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=11)
        project = await repository.create_project("键盘项目", workspace_id)
        storage = MemoryProjectAssetStorage()
        service = ProjectAssetService(
            repository,
            storage,
            LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
        )

        source = await service.upload_asset(
            project.id, "source", _png(), "image/png", "keyboard.png"
        )
        white_background = await service.upload_asset(
            project.id,
            "white_background",
            _png("white"),
            "image/png",
            "keyboard-white.png",
            source_asset_id=source.id,
        )
        preview = await service.get_preview(project.id, white_background.id)

        assert source.kind == "source"
        assert white_background.source_asset_id == source.id
        assert preview.content_type == "image/png"
        assert preview.data == _png("white")

    asyncio.run(run())


def test_project_asset_service_accepts_external_white_background_without_source() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=11)
        project = await repository.create_project("外部白底图", workspace_id)
        service = ProjectAssetService(
            repository,
            MemoryProjectAssetStorage(),
            LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
        )

        asset = await service.upload_asset(
            project.id,
            "white_background",
            _png("white"),
            "image/png",
            "external-white.png",
        )

        assert asset.kind == "white_background"
        assert asset.source_asset_id is None

    asyncio.run(run())


def test_project_asset_service_selects_and_clears_current_asset() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=11)
        project = await repository.create_project("键盘项目", workspace_id)
        service = ProjectAssetService(
            repository,
            MemoryProjectAssetStorage(),
            LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
        )
        source = await service.upload_asset(
            project.id, "source", _png(), "image/png", "keyboard.png"
        )

        selected = await service.select_asset(project.id, "source", source.id)
        selections = await service.get_selections(project.id)
        cleared = await service.clear_selection(project.id, "source")

        assert selected.id == source.id
        assert selections == {"source": source.id}
        assert cleared is True
        assert await service.get_selections(project.id) == {}

    asyncio.run(run())


def test_project_asset_service_replays_upload_without_duplicate_object() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=11)
        project = await repository.create_project("键盘项目", workspace_id)
        storage = MemoryProjectAssetStorage()
        service = ProjectAssetService(
            repository,
            storage,
            LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
            idempotency_store=MemoryIdempotencyStore(),
        )

        first = await service.upload_asset(
            project.id, "source", _png(), "image/png", "keyboard.png", idempotency_key="upload-key"
        )
        replay = await service.upload_asset(
            project.id, "source", _png(), "image/png", "keyboard.png", idempotency_key="upload-key"
        )

        assert replay.id == first.id
        assert len(storage.objects) == 1
        assert len(await repository.list_assets(project.id, workspace_id)) == 1

        try:
            await service.upload_asset(
                project.id, "source", _png("blue"), "image/png", "keyboard.png", idempotency_key="upload-key"
            )
        except AppError as exc:
            assert exc.code == "IDEMPOTENCY_KEY_CONFLICT"
        else:
            raise AssertionError("同一上传键不得绑定不同图片")

    asyncio.run(run())


def test_project_asset_service_compensates_object_when_metadata_write_fails() -> None:
    class FailingRepository(InMemoryProjectRepository):
        async def create_asset(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

    async def run() -> None:
        repository = FailingRepository()
        workspace_id = UUID(int=11)
        project = await repository.create_project("键盘项目", workspace_id)
        storage = MemoryProjectAssetStorage()
        service = ProjectAssetService(
            repository,
            storage,
            LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
        )

        try:
            await service.upload_asset(
                project.id, "source", _png(), "image/png", "keyboard.png"
            )
        except RuntimeError as exc:
            assert str(exc) == "database unavailable"
        else:
            raise AssertionError("元数据写入失败必须向上传播")

        assert storage.objects == {}

    asyncio.run(run())


def test_project_asset_service_protects_source_versions_and_cleans_unreferenced_object() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=11)
        project = await repository.create_project("键盘项目", workspace_id)
        storage = MemoryProjectAssetStorage()
        service = ProjectAssetService(
            repository,
            storage,
            LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
        )
        source = await service.upload_asset(project.id, "source", _png(), "image/png", "source.png")
        white = await service.upload_asset(
            project.id, "white_background", _png("white"), "image/png", "white.png", source_asset_id=source.id
        )

        try:
            await service.delete_asset(project.id, source.id)
        except AppError as exc:
            assert exc.code == "ASSET_IN_USE"
        else:
            raise AssertionError("仍被白底图引用的源图不得删除")

        deleted = await service.delete_asset(project.id, white.id)
        object_record = await repository.get_object(white.object_id, workspace_id)
        source_object = await repository.get_object(source.object_id, workspace_id)

        assert deleted.state == "deleted"
        assert object_record is not None
        assert object_record.state == "cleaned"
        assert source_object is not None
        assert set(storage.objects) == {source_object.storage_key}

    asyncio.run(run())


def test_project_asset_service_marks_failed_object_cleanup_for_retry() -> None:
    class FailingDeleteStorage(MemoryProjectAssetStorage):
        async def delete(self, key: str) -> None:
            raise RuntimeError("storage unavailable")

    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=11)
        project = await repository.create_project("键盘项目", workspace_id)
        storage = FailingDeleteStorage()
        service = ProjectAssetService(
            repository,
            storage,
            LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
        )
        asset = await service.upload_asset(project.id, "source", _png(), "image/png", "source.png")

        await service.delete_asset(project.id, asset.id)
        object_record = await repository.get_object(asset.object_id, workspace_id)

        assert object_record is not None
        assert object_record.state == "cleanup_pending"

    asyncio.run(run())


def test_project_asset_service_releases_derived_assets_before_source_assets() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=11)
        project = await repository.create_project("键盘项目", workspace_id)
        storage = MemoryProjectAssetStorage()
        service = ProjectAssetService(
            repository,
            storage,
            LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")),
        )
        source = await service.upload_asset(project.id, "source", _png(), "image/png", "source.png")
        await service.upload_asset(
            project.id, "white_background", _png("white"), "image/png", "white.png", source_asset_id=source.id
        )

        await service.delete_project_assets(project.id)

        assert await repository.list_assets(project.id, workspace_id) == []
        assert storage.objects == {}

    asyncio.run(run())


def test_project_cleanup_overlaps_independent_io_with_a_bounded_limit() -> None:
    class DelayedStorage(MemoryProjectAssetStorage):
        active = 0
        peak = 0

        async def delete(self, key: str) -> None:
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.02)
                await super().delete(key)
            finally:
                self.active -= 1

    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=11)
        project = await repository.create_project("清理性能", workspace_id)
        storage = DelayedStorage()
        service = ProjectAssetService(repository, storage, LocalSingleUserIdentityProvider(
            IdentityContext(UUID(int=1), workspace_id, "owner")
        ))
        for index in range(12):
            await service.upload_asset(project.id, "source", _png(), "image/png", f"{index}.png")
        await service.delete_project_assets(project.id)
        assert 1 < storage.peak <= 4
        assert storage.active == 0
        assert await repository.list_assets(project.id, workspace_id) == []
        assert storage.objects == {}

    asyncio.run(run())


def test_project_assets_are_linked_to_project_archive_as_they_are_created() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=41)
        identity = LocalSingleUserIdentityProvider(
            IdentityContext(UUID(int=1), workspace_id, "owner")
        )
        project = await repository.create_project("全资产项目", workspace_id)
        product_library = ProductLibraryService(identity)
        coordinator = ProjectArchiveCoordinator(product_library)
        service = ProjectAssetService(
            repository,
            MemoryProjectAssetStorage(),
            identity,
            project_archive=coordinator,
        )

        source = await service.upload_asset(
            project.id, "source", _png(), "image/png", "source.png"
        )
        white = await service.upload_asset(
            project.id,
            "white_background",
            _png("white"),
            "image/png",
            "white.png",
        )
        generated = await service.create_generated_asset(
            project.id,
            _png("blue"),
            "image/png",
            "hero.png",
            source_asset_id=source.id,
            generation_snapshot_id=UUID(int=42),
        )

        product = await product_library.get_project_product(project.id)
        assert product is not None
        assert {
            item.project_asset_id
            for item in await product_library.list_product_asset_links(product.id)
        } == {source.id, white.id, generated.id}

    asyncio.run(run())


def test_archive_link_failure_keeps_saved_project_asset_for_backfill() -> None:
    class FailingArchive:
        async def link_project_asset(self, project, asset):
            raise RuntimeError("archive unavailable")

    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=43)
        project = await repository.create_project("保留资产项目", workspace_id)
        storage = MemoryProjectAssetStorage()
        service = ProjectAssetService(
            repository,
            storage,
            LocalSingleUserIdentityProvider(
                IdentityContext(UUID(int=1), workspace_id, "owner")
            ),
            project_archive=FailingArchive(),
        )

        try:
            await service.upload_asset(
                project.id, "source", _png(), "image/png", "source.png"
            )
        except RuntimeError as exc:
            assert str(exc) == "archive unavailable"
        else:
            raise AssertionError("归档关联失败必须向调用方返回错误")

        assets = await repository.list_assets(project.id, workspace_id)
        assert len(assets) == 1
        assert len(storage.objects) == 1

    asyncio.run(run())


def test_deleting_project_asset_unlinks_it_from_project_archive() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        workspace_id = UUID(int=44)
        identity = LocalSingleUserIdentityProvider(
            IdentityContext(UUID(int=1), workspace_id, "owner")
        )
        project = await repository.create_project("删除关联项目", workspace_id)
        product_library = ProductLibraryService(identity)
        coordinator = ProjectArchiveCoordinator(product_library)
        service = ProjectAssetService(
            repository,
            MemoryProjectAssetStorage(),
            identity,
            project_archive=coordinator,
        )
        asset = await service.upload_asset(
            project.id, "source", _png(), "image/png", "source.png"
        )
        product = await product_library.get_project_product(project.id)
        assert product is not None

        await service.delete_asset(project.id, asset.id)

        assert await product_library.list_product_asset_links(product.id) == []

    asyncio.run(run())
