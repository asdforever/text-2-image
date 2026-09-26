import asyncio
from uuid import UUID

from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.project_service import ProjectService
from backend.app.application.product_library_service import ProductLibraryService
from backend.app.application.project_archive_service import ProjectArchiveCoordinator
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.project_repository import InMemoryProjectRepository


def _service(repository, workspace_id: int, store=None) -> ProjectService:
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=workspace_id), UUID(int=workspace_id), "owner")
    )
    return ProjectService(repository, identity, store or MemoryIdempotencyStore())


def test_project_service_creates_trimmed_project_and_replays_idempotent_request() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        store = MemoryIdempotencyStore()
        service = _service(repository, 11, store)

        created = await service.create_project("  键盘项目  ", "project-key")
        replay = await service.create_project("键盘项目", "project-key")

        assert created.name == "键盘项目"
        assert replay.id == created.id
        assert [item.id for item in await service.list_projects()] == [created.id]

        try:
            await service.create_project("不同项目", "project-key")
        except AppError as exc:
            assert exc.code == "IDEMPOTENCY_KEY_CONFLICT"
        else:
            raise AssertionError("同一幂等键不得创建不同项目")

    asyncio.run(run())


def test_project_service_rejects_blank_name_and_hides_other_workspace_project() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        owner = _service(repository, 11)
        outsider = _service(repository, 22)

        try:
            await owner.create_project("   ")
        except AppError as exc:
            assert exc.code == "INVALID_PROJECT_NAME"
        else:
            raise AssertionError("空项目名称必须被拒绝")

        created = await owner.create_project("受保护项目")
        assert await outsider.get_project(created.id) is None
        assert await outsider.archive_project(created.id) is None
        assert (await owner.get_project(created.id)).status == "active"

    asyncio.run(run())


def test_project_service_replays_archive_and_delete_requests() -> None:
    async def run() -> None:
        repository = InMemoryProjectRepository()
        store = MemoryIdempotencyStore()
        service = _service(repository, 11, store)
        archived_target = await service.create_project("归档目标")
        deleted_target = await service.create_project("删除目标")

        first_archive = await service.archive_project(archived_target.id, "archive-key")
        replay_archive = await service.archive_project(archived_target.id, "archive-key")
        first_delete = await service.delete_project(deleted_target.id, "delete-key")
        replay_delete = await service.delete_project(deleted_target.id, "delete-key")

        assert first_archive is not None
        assert replay_archive is not None
        assert first_archive.id == replay_archive.id
        assert first_archive.status == "archived"
        assert first_delete is True
        assert replay_delete is True

    asyncio.run(run())


def test_project_creation_ensures_one_product_archive_before_returning() -> None:
    async def run() -> None:
        workspace_id = UUID(int=31)
        identity = LocalSingleUserIdentityProvider(
            IdentityContext(UUID(int=1), workspace_id, "owner")
        )
        repository = InMemoryProjectRepository()
        product_library = ProductLibraryService(identity)
        coordinator = ProjectArchiveCoordinator(product_library)
        service = ProjectService(
            repository,
            identity,
            MemoryIdempotencyStore(),
            project_archive=coordinator,
        )

        regular = await service.create_project("普通项目")
        idempotent = await service.create_project("幂等项目", "create-project-archive")
        replay = await service.create_project("幂等项目", "create-project-archive")

        regular_product = await product_library.get_project_product(regular.id)
        idempotent_product = await product_library.get_project_product(idempotent.id)
        products = list(product_library.products.values())
        assert regular_product is not None
        assert idempotent_product is not None
        assert replay.id == idempotent.id
        assert len(products) == 2

    asyncio.run(run())


def test_project_archive_also_archives_its_product_entry() -> None:
    async def run() -> None:
        workspace_id = UUID(int=32)
        identity = LocalSingleUserIdentityProvider(
            IdentityContext(UUID(int=1), workspace_id, "owner")
        )
        repository = InMemoryProjectRepository()
        product_library = ProductLibraryService(identity)
        coordinator = ProjectArchiveCoordinator(product_library)
        service = ProjectService(
            repository,
            identity,
            MemoryIdempotencyStore(),
            project_archive=coordinator,
        )
        project = await service.create_project("待归档项目")
        product = await product_library.get_project_product(project.id)
        assert product is not None

        archived = await service.archive_project(project.id, "archive-project-product")
        replay = await service.archive_project(project.id, "archive-project-product")

        assert archived is not None
        assert replay is not None
        assert product.archived_at is not None
        assert await product_library.get_project_product(project.id) is None

    asyncio.run(run())
