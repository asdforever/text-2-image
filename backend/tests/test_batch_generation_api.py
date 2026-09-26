from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


class BatchService:
    async def compile_prompt_batch(self, project_id, payload, idempotency_key):
        self.compile = (project_id, payload, idempotency_key)
        return _batch()


class ConfirmationService:
    async def confirm_batch(self, project_id, batch_id, prompts, idempotency_key):
        self.confirm = (project_id, batch_id, prompts, idempotency_key)
        return _batch(status="queued")


class BatchRepository:
    def __init__(self) -> None:
        self.status = "awaiting_confirmation"

    async def get_batch_detail(self, batch_id, _workspace_id):
        if batch_id != UUID(int=55):
            return None
        return _detail(self.status)

    async def cancel_batch(self, batch_id, _workspace_id):
        assert batch_id == UUID(int=55)
        self.status = "cancelled"
        return _batch(status="cancelled")

    async def retry_slot(self, slot_id, _workspace_id):
        assert slot_id == UUID(int=77)
        return _detail().slots[0]


@pytest.mark.asyncio
async def test_batch_api_compiles_confirms_reads_cancels_and_retries_slots() -> None:
    compile_service = BatchService()
    confirm_service = ConfirmationService()
    app = create_app(
        settings=Settings(_env_file=None), repository=InMemoryRepository(), storage=MemoryObjectStorage(),
        batch_generation_repository=BatchRepository(),
        batch_generation_service=compile_service,
        batch_generation_confirmation_service=confirm_service,
    )
    project_id = UUID(int=22)
    batch_id = UUID(int=55)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        compiled = await client.post(
            f"/api/projects/{project_id}/generation-batches/compile",
            headers={"Idempotency-Key": "compile"},
            json={
                "sourceAssetId": str(UUID(int=33)), "marketId": "taobao", "modelId": "gpt-image-2-5",
                "styleId": "precision", "aspectRatio": "1:1", "resolution": "标准 1K",
                "outputLanguage": "中文", "modules": [
                    {"moduleId": "hero-kv", "resultCount": 3, "moduleParameters": []},
                    {"moduleId": "hero-scene", "resultCount": 2, "moduleParameters": []},
                ],
            },
        )
        read = await client.get(f"/api/projects/{project_id}/generation-batches/{batch_id}")
        confirmed = await client.post(
            f"/api/projects/{project_id}/generation-batches/{batch_id}/confirm",
            headers={"Idempotency-Key": "confirm"},
            json={"moduleTaskPrompts": {"hero-kv": "KV", "hero-scene": "场景"}},
        )
        cancelled = await client.post(f"/api/projects/{project_id}/generation-batches/{batch_id}/cancel")
        retried = await client.post(
            f"/api/projects/{project_id}/generation-batches/{batch_id}/slots/{UUID(int=77)}/retry"
        )

    assert compiled.status_code == 201
    assert read.status_code == 200
    assert read.json()["data"]["progress"]["total"] == 5
    assert confirmed.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert retried.json()["data"]["slot"]["status"] == "queued"
    assert compile_service.compile[2] == "compile"
    assert confirm_service.confirm[2] == {"hero-kv": "KV", "hero-scene": "场景"}


def _batch(status="awaiting_confirmation"):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=UUID(int=55), project_id=UUID(int=22), source_asset_id=UUID(int=33), status=status,
        snapshot={}, created_at=now, updated_at=now, confirmed_at=None, completed_at=None,
    )


def _detail(status="awaiting_confirmation"):
    batch = _batch(status)
    module = SimpleNamespace(
        id=UUID(int=66), module_key="hero-kv", requested_image_count=3,
        snapshot={"constraints": {}}, compiled_task_prompt="KV", compiler_output={"visibleFacts": []},
        confirmed_task_prompt=None, final_prompt=None, final_prompt_sha256=None,
    )
    slot = SimpleNamespace(
        id=UUID(int=77), batch_id=UUID(int=55), module_task_id=UUID(int=66), module_key="hero-kv", ordinal=1,
        status="queued", generated_asset_id=None, error_code=None, error_message=None,
    )
    progress = SimpleNamespace(total=5, queued=5, leased=0, dispatching=0, succeeded=0, failed=0, cancelled=0, needs_retry=0, completed=0)
    return SimpleNamespace(batch=batch, module_tasks=[module], slots=[slot], progress=progress)
