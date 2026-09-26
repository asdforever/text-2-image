import asyncio
from copy import deepcopy
from uuid import UUID

import httpx

from backend.app.core.config import Settings
from backend.app.generation_config_repository import InMemoryGenerationConfigRepository
from backend.app.main import create_app
from backend.app.prompt_repository import MemoryPromptRepository


def test_publish_idempotency_key_conflicts_after_effective_draft_changes() -> None:
    async def run() -> None:
        app = create_app(settings=Settings(_env_file=None))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            initial = (await client.get("/api/generation-config/draft")).json()["data"]
            first_content = deepcopy(initial["content"])
            first_content["markets"][0]["label"] = "首次发布"
            await client.put(
                "/api/generation-config/draft",
                json={"baseVersion": 1, "content": first_content},
            )
            first = await client.post(
                "/api/generation-config/publish",
                headers={"Idempotency-Key": "same-publish-key"},
            )
            second_content = deepcopy(first.json()["data"]["content"])
            second_content["markets"][0]["label"] = "第二次发布"
            await client.put(
                "/api/generation-config/draft",
                json={"baseVersion": 2, "content": second_content},
            )
            conflict = await client.post(
                "/api/generation-config/publish",
                headers={"Idempotency-Key": "same-publish-key"},
            )

        assert first.status_code == 200
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"

    asyncio.run(run())


def test_configuration_responses_hide_workspace_and_prompt_internal_fields() -> None:
    async def run() -> None:
        prompts = MemoryPromptRepository()
        template = await prompts.create_template(
            code="private-prompt",
            name="安全绑定",
            kind="generation",
            kind_name="图片生成",
            execution_target="image",
        )
        version = await prompts.create_version(
            template,
            body="PRIVATE PROMPT BODY MUST NOT LEAK",
        )
        app = create_app(
            settings=Settings(_env_file=None, local_workspace_id=UUID(int=11)),
            generation_config_repository=InMemoryGenerationConfigRepository(),
            prompt_repository=prompts,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            draft = (await client.get("/api/generation-config/draft")).json()["data"]
            content = deepcopy(draft["content"])
            content["marketBindings"]["taobao"] = {
                "promptTemplateId": str(template.id),
                "promptVersionId": str(version.id),
                "body": "CLIENT INJECTED BODY",
                "filePath": "C:/private/prompt.md",
            }
            await client.put(
                "/api/generation-config/draft",
                json={"baseVersion": 1, "content": content},
            )
            published = await client.post("/api/generation-config/publish")
            resolved = await client.get("/api/generation-config/resolve")

        for response in (published, resolved):
            assert response.status_code == 200
            assert "workspaceId" not in response.text
            assert "PRIVATE PROMPT BODY" not in response.text
            assert "CLIENT INJECTED BODY" not in response.text
            assert "private/prompt.md" not in response.text

    asyncio.run(run())
