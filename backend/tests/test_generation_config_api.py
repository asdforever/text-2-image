import asyncio
from copy import deepcopy
from uuid import UUID

import httpx

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.prompt_repository import MemoryPromptRepository


def test_generation_config_api_exposes_draft_publish_history_and_resolve() -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None, local_workspace_id=UUID(int=11)),
            prompt_repository=MemoryPromptRepository(),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            published = await client.get(
                "/api/generation-config", headers={"X-Request-ID": "config-api-1"}
            )
            draft = await client.get("/api/generation-config/draft")
            content = deepcopy(draft.json()["data"]["content"])
            content["markets"][0]["label"] = "淘宝编辑态"
            saved = await client.put(
                "/api/generation-config/draft",
                json={
                    "baseVersion": draft.json()["data"]["baseVersion"],
                    "content": content,
                    "workspaceId": str(UUID(int=22)),
                },
                headers={"Idempotency-Key": "config-save-1"},
            )
            still_published = await client.get("/api/generation-config")
            released = await client.post(
                "/api/generation-config/publish",
                headers={"Idempotency-Key": "config-publish-1"},
            )
            replay = await client.post(
                "/api/generation-config/publish",
                headers={"Idempotency-Key": "config-publish-1"},
            )
            history = await client.get("/api/generation-config/versions/1")
            resolved = await client.get("/api/generation-config/resolve")

        assert published.status_code == 200
        assert published.json()["requestId"] == "config-api-1"
        assert published.json()["data"]["version"] == 1
        assert draft.json()["data"]["baseVersion"] == 1
        assert saved.status_code == 200
        assert saved.json()["data"]["content"]["markets"][0]["label"] == "淘宝编辑态"
        assert "workspaceId" not in saved.json()["data"]
        assert still_published.json()["data"]["content"]["markets"][0]["label"] == "淘宝"
        assert released.json()["data"]["version"] == 2
        assert replay.json()["data"]["version"] == 2
        assert history.json()["data"]["version"] == 1
        assert resolved.json()["data"]["configVersion"] == 2
        assert resolved.json()["data"]["config"]["markets"][0]["label"] == "淘宝编辑态"

    asyncio.run(run())


def test_generation_config_api_discards_draft_and_returns_uniform_errors() -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            prompt_repository=MemoryPromptRepository(),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            draft = await client.get("/api/generation-config/draft")
            content = deepcopy(draft.json()["data"]["content"])
            content["styleCategories"][0]["styles"].extend([
                {"id": "four", "label": "第四种", "description": "允许范围"},
                {"id": "five", "label": "第五种", "description": "超出限制"},
            ])
            invalid = await client.put(
                "/api/generation-config/draft",
                json={"baseVersion": 1, "content": content},
            )
            discarded = await client.delete(
                "/api/generation-config/draft",
                headers={"Idempotency-Key": "config-discard-1"},
            )
            missing = await client.get("/api/generation-config/versions/99")

        assert invalid.status_code == 400
        assert set(invalid.json()) == {"error", "requestId"}
        assert invalid.json()["error"]["code"] == "GENERATION_CONFIG_INVALID"
        assert discarded.status_code == 200
        assert discarded.json()["data"]["content"]["markets"][0]["label"] == "淘宝"
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "GENERATION_CONFIG_VERSION_NOT_FOUND"

    asyncio.run(run())
