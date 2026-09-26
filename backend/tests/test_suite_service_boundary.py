from uuid import UUID

from backend.app.core.config import Settings
import asyncio

import httpx

from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.application.ports import MemoryIdempotencyStore, SystemClock
from backend.app.application.suite_service import SuiteService
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


def test_app_factory_composes_suite_service_with_replaceable_dependencies() -> None:
    repository = InMemoryRepository()
    storage = MemoryObjectStorage()
    app = create_app(
        settings=Settings(_env_file=None),
        repository=repository,
        storage=storage,
    )

    service = app.state.suite_service

    assert service.repository is repository
    assert service.storage is storage
    assert isinstance(service.identity_provider, LocalSingleUserIdentityProvider)
    assert service.identity_provider.get_context() == IdentityContext(
        actor_id=UUID("11111111-1111-4111-8111-111111111111"),
        workspace_id=UUID("22222222-2222-4222-8222-222222222222"),
        role="owner",
    )


def test_suite_service_scopes_create_list_and_get_to_server_workspace() -> None:
    async def run() -> None:
        repository = InMemoryRepository()
        workspace_a = LocalSingleUserIdentityProvider(
            IdentityContext(UUID(int=1), UUID(int=11), "owner")
        )
        workspace_b = LocalSingleUserIdentityProvider(
            IdentityContext(UUID(int=2), UUID(int=22), "owner")
        )
        service_a = SuiteService(repository, MemoryObjectStorage(), SystemClock(), workspace_a, MemoryIdempotencyStore())
        service_b = SuiteService(repository, MemoryObjectStorage(), SystemClock(), workspace_b, MemoryIdempotencyStore())

        created = await service_a.create_suite("A 项目", "create-a")

        assert created.workspace_id == UUID(int=11)
        assert [item.id for item in await service_a.list_suites()] == [created.id]
        assert await service_b.list_suites() == []
        assert await service_b.get_suite(created.id) is None

    asyncio.run(run())


def test_public_suite_api_keeps_contract_and_ignores_spoofed_workspace() -> None:
    async def run() -> None:
        repository = InMemoryRepository()
        settings = Settings(_env_file=None, local_workspace_id=UUID(int=11))
        app = create_app(settings=settings, repository=repository, storage=MemoryObjectStorage())

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                "/api/suites",
                json={"name": "兼容项目", "workspaceId": str(UUID(int=22))},
                headers={"X-Workspace-Id": str(UUID(int=22)), "Idempotency-Key": "suite-compatible"},
            )
            listed = await client.get("/api/suites")
            fetched = await client.get(f"/api/suites/{created.json()['data']['id']}")

        assert created.status_code == 201
        assert listed.status_code == 200
        assert fetched.status_code == 200
        assert created.json()["data"]["name"] == "兼容项目"
        assert "workspaceId" not in created.json()["data"]
        assert next(iter(repository.suites.values())).workspace_id == UUID(int=11)

    asyncio.run(run())
