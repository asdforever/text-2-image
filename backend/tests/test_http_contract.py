import asyncio
from uuid import UUID

import httpx

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.storage import MemoryObjectStorage


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


def test_success_validation_not_found_and_dependency_errors_share_contract() -> None:
    class BrokenRepository(InMemoryRepository):
        async def ready(self) -> bool:
            return False

    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            repository=BrokenRepository(),
            storage=MemoryObjectStorage(),
        )
        async with _client(app) as client:
            health = await client.get(
                "/api/health", headers={"X-Request-ID": "request-contract-1"}
            )
            invalid = await client.get("/api/suites/not-a-uuid")
            missing = await client.get(f"/api/suites/{UUID(int=999)}")
            unavailable = await client.get("/api/ready")

        assert health.json() == {
            "data": {"ready": True},
            "requestId": "request-contract-1",
        }
        assert health.headers["X-Request-ID"] == "request-contract-1"
        for response in (invalid, missing, unavailable):
            assert set(response.json()) == {"error", "requestId"}
            assert set(response.json()["error"]) == {"code", "message"}
            assert response.json()["requestId"] == response.headers["X-Request-ID"]
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "INVALID_REQUEST"
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "INVALID_SUITE_ID"
        assert unavailable.status_code == 503
        assert unavailable.json()["error"]["code"] == "DEPENDENCY_NOT_READY"

    asyncio.run(run())


def test_unhandled_dependency_error_is_sanitized_and_correlated() -> None:
    class BrokenAssetService:
        async def list_libraries(self):
            raise RuntimeError("postgresql://user:password@db/private")

    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
            asset_service=BrokenAssetService(),
        )
        async with _client(app) as client:
            response = await client.get(
                "/api/asset-libraries", headers={"X-Request-ID": "request-failure-1"}
            )

        assert response.status_code == 500
        assert response.json() == {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "internal server error",
            },
            "requestId": "request-failure-1",
        }
        assert "password" not in response.text
        assert response.headers["X-Request-ID"] == "request-failure-1"

    asyncio.run(run())


def test_invalid_request_id_is_replaced() -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
        )
        invalid_request_id = "x" * 200
        async with _client(app) as client:
            response = await client.get(
                "/api/health", headers={"X-Request-ID": invalid_request_id}
            )

        returned = response.json()["requestId"]
        assert returned != invalid_request_id
        assert UUID(returned)
        assert response.headers["X-Request-ID"] == returned

    asyncio.run(run())


def test_liveness_stays_up_while_readiness_names_failed_dependencies() -> None:
    class BrokenRepository(InMemoryRepository):
        async def readiness_checks(self):
            return {"database": False, "schema": False}

    class BrokenStorage(MemoryObjectStorage):
        async def ready(self) -> bool:
            return False

    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            repository=BrokenRepository(),
            storage=BrokenStorage(),
        )
        async with _client(app) as client:
            health = await client.get("/api/health")
            ready = await client.get("/api/ready")

        assert health.status_code == 200
        assert ready.status_code == 503
        assert ready.json()["error"] == {
            "code": "DEPENDENCY_NOT_READY",
            "message": "service dependencies are not ready: database, schema, storage",
        }

    asyncio.run(run())


def test_readiness_reports_unavailable_project_domain() -> None:
    class BrokenProjectRepository(InMemoryProjectRepository):
        async def ready(self) -> bool:
            return False

    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
            project_repository=BrokenProjectRepository(),
        )
        async with _client(app) as client:
            ready = await client.get("/api/ready")

        assert ready.status_code == 503
        assert ready.json()["error"]["message"] == "service dependencies are not ready: projectDomain"

    asyncio.run(run())
