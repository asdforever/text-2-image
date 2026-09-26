from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


class RecordingHeroService:
    def __init__(self) -> None:
        self.compile_calls = []
        self.get_calls = []
        self.confirm_calls = []
        self.task = _task()

    async def compile_prompt(self, project_id, payload, idempotency_key):
        self.compile_calls.append((project_id, payload, idempotency_key))
        return self.task

    async def get_task(self, project_id, task_id):
        self.get_calls.append((project_id, task_id))
        if project_id != self.task.project_id or task_id != self.task.id:
            raise AppError("HERO_GENERATION_NOT_FOUND", "hero generation task does not exist", 404)
        return self.task

    async def confirm_generation(
        self, project_id, task_id, *, task_prompt, idempotency_key
    ):
        self.confirm_calls.append((project_id, task_id, task_prompt, idempotency_key))
        self.task.status = "succeeded"
        self.task.confirmed_task_prompt = task_prompt or self.task.compiled_task_prompt
        self.task.final_prompt = "固定约束\n" + self.task.confirmed_task_prompt
        self.task.final_prompt_sha256 = "f" * 64
        self.task.generated_asset_id = UUID(int=44)
        return self.task


@pytest.mark.asyncio
async def test_compile_api_accepts_only_stage_3a_fields_and_returns_confirmation_view() -> None:
    service = RecordingHeroService()
    app = _app(service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/projects/{UUID(int=22)}/hero-generations/compile",
            headers={"Idempotency-Key": "compile-key", "X-Request-ID": "hero-compile-1"},
            json={
                "sourceAssetId": str(UUID(int=33)),
                "marketId": "taobao",
                "modelId": "gpt-image-2-5",
                "styleId": "precision",
                "moduleId": "hero-kv",
                "aspectRatio": "1:1",
                "resolution": "标准 1K",
                "outputLanguage": "中文",
                "customStyle": "冷灰背景",
                "moduleParameters": [{"key": "核心卖点", "value": "轻量佩戴"}],
                "resultCount": 1,
            },
        )

    assert response.status_code == 201
    assert response.json()["requestId"] == "hero-compile-1"
    data = response.json()["data"]
    assert data["id"] == str(UUID(int=55))
    assert data["status"] == "awaiting_confirmation"
    assert data["compiledTaskPrompt"] == "编译后的实时任务提示词"
    assert data["visibleFacts"] == ["黑色主体"]
    assert data["unconfirmedItems"] == ["材质未知"]
    assert data["constraints"]["market"]["content"] == "淘宝约束"
    assert data["generatedAssetPreviewUrl"] is None
    assert "workspaceId" not in data
    assert "compileFingerprint" not in data
    project_id, payload, key = service.compile_calls[0]
    assert project_id == UUID(int=22)
    assert payload.source_asset_id == UUID(int=33)
    assert payload.module_parameters == [{"key": "核心卖点", "value": "轻量佩戴"}]
    assert key == "compile-key"


@pytest.mark.asyncio
async def test_compile_api_rejects_multiple_results_and_client_owned_constraints() -> None:
    service = RecordingHeroService()
    app = _app(service)
    base_payload = {
        "sourceAssetId": str(UUID(int=33)),
        "marketId": "taobao",
        "modelId": "gpt-image-2-5",
        "styleId": "precision",
        "moduleId": "hero-kv",
        "aspectRatio": "1:1",
        "resolution": "标准 1K",
        "outputLanguage": "中文",
        "moduleParameters": [],
        "resultCount": 2,
        "constraints": {"market": "客户端伪造约束"},
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/projects/{UUID(int=22)}/hero-generations/compile",
            headers={"Idempotency-Key": "invalid"},
            json=base_payload,
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert service.compile_calls == []


@pytest.mark.asyncio
async def test_task_and_confirm_apis_preserve_project_boundary_and_edit_only_task_prompt() -> None:
    service = RecordingHeroService()
    app = _app(service)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        fetched = await client.get(
            f"/api/projects/{UUID(int=22)}/hero-generations/{UUID(int=55)}"
        )
        confirmed = await client.post(
            f"/api/projects/{UUID(int=22)}/hero-generations/{UUID(int=55)}/confirm",
            headers={"Idempotency-Key": "confirm-key"},
            json={"taskPrompt": "用户编辑后的实时任务提示词"},
        )
        rejected = await client.post(
            f"/api/projects/{UUID(int=22)}/hero-generations/{UUID(int=55)}/confirm",
            headers={"Idempotency-Key": "bad-confirm"},
            json={"taskPrompt": "任务", "marketConstraint": "删除淘宝约束"},
        )
        wrong_project = await client.get(
            f"/api/projects/{UUID(int=99)}/hero-generations/{UUID(int=55)}"
        )

    assert fetched.status_code == 200
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "succeeded"
    assert confirmed.json()["data"]["generatedAssetId"] == str(UUID(int=44))
    assert confirmed.json()["data"]["generatedAssetPreviewUrl"] == (
        f"/api/projects/{UUID(int=22)}/assets/{UUID(int=44)}/preview"
    )
    assert service.confirm_calls == [
        (
            UUID(int=22),
            UUID(int=55),
            "用户编辑后的实时任务提示词",
            "confirm-key",
        )
    ]
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "INVALID_REQUEST"
    assert wrong_project.status_code == 404
    assert wrong_project.json()["error"]["code"] == "HERO_GENERATION_NOT_FOUND"


def _app(service):
    return create_app(
        settings=Settings(_env_file=None),
        repository=InMemoryRepository(),
        storage=MemoryObjectStorage(),
        hero_generation_service=service,
    )


def _task():
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=UUID(int=55),
        workspace_id=UUID(int=11),
        project_id=UUID(int=22),
        source_asset_id=UUID(int=33),
        status="awaiting_confirmation",
        snapshot={
            "constraints": {
                "authenticity": {"content": "真实性约束"},
                "market": {"content": "淘宝约束"},
                "style": {"content": "冷调精密约束"},
            },
            "selection": {"module": {"label": "首屏 KV"}},
        },
        compiled_task_prompt="编译后的实时任务提示词",
        compiler_output={
            "taskPrompt": "编译后的实时任务提示词",
            "visibleFacts": ["黑色主体"],
            "unconfirmedItems": ["材质未知"],
        },
        confirmed_task_prompt=None,
        final_prompt=None,
        final_prompt_sha256=None,
        provider_request=None,
        generated_asset_id=None,
        error_code=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        confirmed_at=None,
        completed_at=None,
    )
