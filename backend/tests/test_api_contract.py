import asyncio
from io import BytesIO
from uuid import UUID

import httpx
from PIL import Image

from backend.app.main import create_app
from backend.app.core.config import Settings
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


def image_bytes() -> bytes:
    image = Image.new("RGB", (4, 3), "red")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def client() -> httpx.AsyncClient:
    app = create_app(
        settings=Settings(_env_file=None),
        repository=InMemoryRepository(),
        storage=MemoryObjectStorage(),
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_create_suite_and_retrieve_aggregate() -> None:
    asyncio.run(_test_create_suite_and_retrieve_aggregate())


async def _test_create_suite_and_retrieve_aggregate() -> None:
    async with client() as api:
        created = await api.post("/api/suites", json={"name": "Demo"}, headers={"Idempotency-Key": "suite-1"})
        assert created.status_code == 201
        suite_id = created.json()["data"]["id"]
        fetched = await api.get(f"/api/suites/{suite_id}")
        assert fetched.status_code == 200
        assert fetched.json()["data"]["inputImages"] == []
        assert fetched.json()["requestId"]


def test_blank_name_uses_error_envelope() -> None:
    asyncio.run(_test_blank_name_uses_error_envelope())


async def _test_blank_name_uses_error_envelope() -> None:
    async with client() as api:
        response = await api.post("/api/suites", json={"name": "  "})
        assert response.status_code == 400
        assert set(response.json()) == {"error", "requestId"}


def test_upload_and_preview_image() -> None:
    asyncio.run(_test_upload_and_preview_image())


async def _test_upload_and_preview_image() -> None:
    async with client() as api:
        suite = await api.post("/api/suites", json={"name": "Images"})
        suite_id = suite.json()["data"]["id"]
        uploaded = await api.post(
            f"/api/suites/{suite_id}/input-images",
            files={"file": ("item.png", image_bytes(), "image/png")},
            headers={"Idempotency-Key": "upload-1"},
        )
        assert uploaded.status_code == 201
        image_id = uploaded.json()["data"]["id"]
        preview = await api.get(f"/api/suites/{suite_id}/input-images/{image_id}/preview/original")
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/png"


def test_duplicate_upload_is_rejected_and_missing_preview_is_404() -> None:
    asyncio.run(_test_duplicate_upload_is_rejected_and_missing_preview_is_404())


async def _test_duplicate_upload_is_rejected_and_missing_preview_is_404() -> None:
    async with client() as api:
        suite = await api.post("/api/suites", json={"name": "Images"})
        suite_id = suite.json()["data"]["id"]
        payload = {"file": ("item.png", image_bytes(), "image/png")}
        first = await api.post(f"/api/suites/{suite_id}/input-images", files=payload)
        assert first.status_code == 201
        second = await api.post(f"/api/suites/{suite_id}/input-images", files=payload)
        assert second.status_code == 409
        missing = await api.get(f"/api/suites/{suite_id}/input-images/{UUID(int=0)}/preview/original")
        assert missing.status_code == 404
        assert set(missing.json()) == {"error", "requestId"}


def test_ready_check_reports_dependency_failure() -> None:
    class BrokenRepository(InMemoryRepository):
        async def ready(self) -> bool: return False

    async def run() -> None:
        api_app = create_app(repository=BrokenRepository(), storage=MemoryObjectStorage())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url="http://test") as api:
            response = await api.get("/api/ready")
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "DEPENDENCY_NOT_READY"

    asyncio.run(run())
