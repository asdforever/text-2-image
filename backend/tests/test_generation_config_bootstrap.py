import asyncio

import httpx

from backend.app.core.config import Settings
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository
from backend.app.main import create_app


class _UnavailableGenerationConfigRepository(InMemoryGenerationConfigRepository):
    async def ready(self) -> bool:
        return False


def test_memory_application_composes_generation_config_and_reports_readiness() -> None:
    async def run() -> None:
        app = create_app(settings=Settings(_env_file=None))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ready = await client.get("/api/ready")
            config = await client.get("/api/generation-config")

        assert ready.status_code == 200
        assert ready.json()["data"]["checks"]["generationConfig"] is True
        assert config.status_code == 200
        assert config.json()["data"]["version"] == 1

    asyncio.run(run())


def test_readiness_names_generation_config_dependency_failure() -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            generation_config_repository=_UnavailableGenerationConfigRepository()
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/ready")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DEPENDENCY_NOT_READY"
        assert "generationConfig" in response.json()["error"]["message"]

    asyncio.run(run())
