import asyncio
from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID

import httpx
from PIL import Image

from backend.app.application.ports import MemoryIdempotencyStore
from backend.app.application.suite_service import SuiteService
from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


def _image_bytes(image_format: str = "PNG") -> bytes:
    image = Image.new("RGB", (8, 6), "red")
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


class _FixedClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 14, 8, 30, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value


def _service(
    repository: InMemoryRepository | None = None,
    storage: MemoryObjectStorage | None = None,
    *,
    max_upload_bytes: int = 1024 * 1024,
) -> tuple[SuiteService, InMemoryRepository, MemoryObjectStorage, _FixedClock]:
    resolved_repository = repository or InMemoryRepository()
    resolved_storage = storage or MemoryObjectStorage()
    clock = _FixedClock()
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(UUID(int=1), UUID(int=11), "owner")
    )
    service = SuiteService(
        resolved_repository,
        resolved_storage,
        clock,
        identity,
        MemoryIdempotencyStore(),
        max_upload_bytes=max_upload_bytes,
    )
    return service, resolved_repository, resolved_storage, clock


def test_service_uploads_original_and_thumbnail_and_serves_preview() -> None:
    async def run() -> None:
        service, _, storage, clock = _service()
        suite = await service.create_suite("图片项目")

        uploaded = await service.upload_input_image(
            suite.id,
            _image_bytes(),
            "image/png",
            "item.png",
            ordinal=None,
            idempotency_key="upload-1",
        )
        original = await service.get_input_image_preview(suite.id, uploaded.id, "original")
        thumbnail = await service.get_input_image_preview(suite.id, uploaded.id, "thumbnail")

        assert uploaded.ordinal == 1
        assert uploaded.created_at == clock.value
        assert original.data == _image_bytes()
        assert original.content_type == "image/png"
        assert thumbnail.content_type == "image/jpeg"
        assert set(storage.objects) == {uploaded.original_key, uploaded.thumbnail_key}

    asyncio.run(run())


def test_service_validates_size_type_and_ordinal_before_writing_objects() -> None:
    async def run() -> None:
        service, _, storage, _ = _service()
        suite = await service.create_suite("校验项目")

        cases = [
            (_image_bytes(), "image/png", 7, "INVALID_ORDINAL"),
            (b"not-an-image", "image/png", 1, "INVALID_IMAGE"),
            (_image_bytes(), "image/jpeg", 1, "MIME_MISMATCH"),
        ]
        for body, content_type, ordinal, expected_code in cases:
            try:
                await service.upload_input_image(
                    suite.id, body, content_type, "item.png", ordinal=ordinal
                )
            except AppError as exc:
                assert exc.code == expected_code
            else:
                raise AssertionError(f"应拒绝输入：{expected_code}")

        limited_service, _, limited_storage, _ = _service(max_upload_bytes=64)
        limited_suite = await limited_service.create_suite("大小校验项目")
        try:
            await limited_service.upload_input_image(
                limited_suite.id, b"x" * 65, "image/png", "item.png", ordinal=1
            )
        except AppError as exc:
            assert exc.code == "IMAGE_TOO_LARGE"
        else:
            raise AssertionError("应拒绝超出上限的文件")

        assert storage.objects == {}
        assert limited_storage.objects == {}

    asyncio.run(run())


def test_service_compensates_both_objects_when_repository_write_fails() -> None:
    class FailingRepository(InMemoryRepository):
        async def add_image(self, suite, image, key=None):
            raise RuntimeError("database unavailable")

    async def run() -> None:
        repository = FailingRepository()
        service, _, storage, _ = _service(repository=repository)
        suite = await service.create_suite("补偿项目")

        try:
            await service.upload_input_image(
                suite.id, _image_bytes(), "image/png", "item.png", ordinal=1
            )
        except RuntimeError as exc:
            assert str(exc) == "database unavailable"
        else:
            raise AssertionError("仓储失败必须向上传播")

        assert storage.objects == {}

    asyncio.run(run())


def test_input_image_http_contract_is_preserved_after_service_migration() -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post("/api/suites", json={"name": "接口项目"})
            suite_id = created.json()["data"]["id"]
            uploaded = await client.post(
                f"/api/suites/{suite_id}/input-images",
                files={"file": ("item.png", _image_bytes(), "image/png")},
                params={"ordinal": 2},
            )
            image_id = uploaded.json()["data"]["id"]
            preview = await client.get(
                f"/api/suites/{suite_id}/input-images/{image_id}/preview/thumbnail"
            )
            missing_kind = await client.get(
                f"/api/suites/{suite_id}/input-images/{image_id}/preview/unknown"
            )

        assert uploaded.status_code == 201
        assert uploaded.json()["data"]["ordinal"] == 2
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/jpeg"
        assert missing_kind.status_code == 404
        assert missing_kind.json()["error"]["code"] == "NOT_FOUND"

    asyncio.run(run())
