import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


class NotReadyBatchRepository:
    async def ready(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_ready_endpoint_reports_batch_generation_dependency() -> None:
    app = create_app(
        settings=Settings(_env_file=None),
        repository=InMemoryRepository(),
        storage=MemoryObjectStorage(),
        batch_generation_repository=NotReadyBatchRepository(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_NOT_READY"
