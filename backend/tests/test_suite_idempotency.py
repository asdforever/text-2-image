import asyncio
from io import BytesIO
from uuid import UUID

from PIL import Image

from backend.app.application.idempotency import MemoryIdempotencyStore
from backend.app.application.ports import SystemClock
from backend.app.application.suite_service import SuiteService
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


def _png(color: str = "red") -> bytes:
    image = Image.new("RGB", (5, 4), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class _CountingRepository(InMemoryRepository):
    def __init__(self) -> None:
        super().__init__()
        self.create_calls = 0
        self.upload_calls = 0

    async def create_suite(self, name, workspace_id, key=None):
        self.create_calls += 1
        return await super().create_suite(name, workspace_id, key)

    async def add_image(self, suite, image, key=None):
        self.upload_calls += 1
        return await super().add_image(suite, image, key)


def _service(repository, storage, store):
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=1), UUID(int=11), "owner")
    )
    return SuiteService(repository, storage, SystemClock(), identity, store)


def test_equivalent_replay_survives_service_recreation_without_duplicate_suite() -> None:
    async def run() -> None:
        repository = _CountingRepository()
        storage = MemoryObjectStorage()
        durable_store = MemoryIdempotencyStore()

        first = await _service(repository, storage, durable_store).create_suite(
            "重放项目", "suite-key"
        )
        replay = await _service(repository, storage, durable_store).create_suite(
            "重放项目", "suite-key"
        )

        assert replay.id == first.id
        assert repository.create_calls == 1
        record = await durable_store.get(
            f"{UUID(int=11)}:POST:/api/suites", "suite-key"
        )
        assert record is not None
        assert record.status == "completed"
        assert record.response_status == 201
        assert record.response_body["id"] == str(first.id)

        try:
            await _service(repository, storage, durable_store).create_suite(
                "不同项目", "suite-key"
            )
        except AppError as exc:
            assert exc.code == "IDEMPOTENCY_KEY_CONFLICT"
        else:
            raise AssertionError("不同载荷必须触发幂等冲突")

    asyncio.run(run())


def test_upload_replay_does_not_duplicate_database_or_storage_side_effects() -> None:
    async def run() -> None:
        repository = _CountingRepository()
        storage = MemoryObjectStorage()
        store = MemoryIdempotencyStore()
        service = _service(repository, storage, store)
        suite = await service.create_suite("上传项目")

        first = await service.upload_input_image(
            suite.id, _png(), "image/png", "item.png", None, "upload-key"
        )
        replay = await service.upload_input_image(
            suite.id, _png(), "image/png", "item.png", None, "upload-key"
        )

        assert replay.id == first.id
        assert repository.upload_calls == 1
        assert len(storage.objects) == 2
        assert len(suite.images) == 1

        try:
            await service.upload_input_image(
                suite.id, _png("blue"), "image/png", "item.png", None, "upload-key"
            )
        except AppError as exc:
            assert exc.code == "IDEMPOTENCY_KEY_CONFLICT"
        else:
            raise AssertionError("同一上传键不能绑定不同图片")

    asyncio.run(run())


def test_concurrent_claim_allows_only_one_owner() -> None:
    class BlockingRepository(_CountingRepository):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def create_suite(self, name, workspace_id, key=None):
            self.create_calls += 1
            self.entered.set()
            await self.release.wait()
            return await InMemoryRepository.create_suite(self, name, workspace_id, key)

    async def run() -> None:
        repository = BlockingRepository()
        service = _service(repository, MemoryObjectStorage(), MemoryIdempotencyStore())
        owner = asyncio.create_task(service.create_suite("并发项目", "shared-key"))
        await repository.entered.wait()
        try:
            await service.create_suite("并发项目", "shared-key")
        except AppError as exc:
            assert exc.code == "IDEMPOTENCY_IN_PROGRESS"
        else:
            raise AssertionError("并发重试不能成为第二个执行者")
        repository.release.set()
        await owner
        assert repository.create_calls == 1

    asyncio.run(run())
