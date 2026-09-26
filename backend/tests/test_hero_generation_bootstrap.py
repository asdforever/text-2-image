from io import BytesIO
from uuid import UUID

import httpx
import pytest
from PIL import Image

from backend.app.core.config import Settings
from backend.app.hero_generation_repository import InMemoryHeroGenerationRepository
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


@pytest.mark.asyncio
async def test_unconfigured_providers_do_not_block_startup_or_readiness() -> None:
    app = create_app(
        settings=Settings(_env_file=None),
        repository=InMemoryRepository(),
        storage=MemoryObjectStorage(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        health = await client.get("/api/health")
        ready = await client.get("/api/ready")
        project = await client.post("/api/projects", json={"name": "耳机主图"})
        project_id = project.json()["data"]["id"]
        source = await client.post(
            f"/api/projects/{project_id}/assets",
            data={"kind": "source"},
            files={"file": ("headphones.png", _png(), "image/png")},
        )
        compile_response = await client.post(
            f"/api/projects/{project_id}/hero-generations/compile",
            headers={"Idempotency-Key": "unconfigured-compile"},
            json={
                "sourceAssetId": source.json()["data"]["id"],
                "marketId": "taobao",
                "modelId": "gpt-image-2-5",
                "styleId": "precision",
                "moduleId": "hero-kv",
                "aspectRatio": "1:1",
                "resolution": "标准 1K",
                "outputLanguage": "中文",
                "moduleParameters": [],
                "resultCount": 1,
            },
        )

    assert health.status_code == 200
    assert ready.status_code == 200
    assert ready.json()["data"]["checks"]["heroGeneration"] is True
    assert compile_response.status_code == 409
    assert compile_response.json()["error"] == {
        "code": "MODEL_CONNECTION_REQUIRED",
        "message": "请先在生成配置中设置模型接口地址和 API Key，并发布配置",
    }
    assert isinstance(app.state.hero_generation_repository, InMemoryHeroGenerationRepository)
    assert app.state.hero_generation_service is not None


@pytest.mark.asyncio
async def test_readiness_reports_hero_generation_repository_failure() -> None:
    class UnreadyHeroRepository(InMemoryHeroGenerationRepository):
        async def ready(self) -> bool:
            return False

    app = create_app(
        settings=Settings(_env_file=None),
        repository=InMemoryRepository(),
        storage=MemoryObjectStorage(),
        hero_generation_repository=UnreadyHeroRepository(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_NOT_READY"
    assert "heroGeneration" in response.json()["error"]["message"]


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (12, 8), (10, 20, 30)).save(output, format="PNG")
    return output.getvalue()
