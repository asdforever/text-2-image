from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.main import create_app
from backend.app.prompt_repository import MemoryPromptRepository


@pytest.mark.asyncio
async def test_new_version_can_change_planning_contract_without_changing_history():
    settings = Settings(_env_file=None, database_url=None, pg_host=None)
    assert settings.database_url is None
    app = create_app(settings, prompt_repository=MemoryPromptRepository())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = (await client.post("/api/prompt-templates", json={
            "code": "style-contract", "name": "风格", "kind": "image_to_image",
            "body": "旧风格正文", "applicability": {"runtimeRole": "image-constraint-fragment"},
        })).json()["data"]
        template_id, first = created["template"]["id"], created["version"]
        response = await client.post(f"/api/prompt-templates/{template_id}/versions", json={
            "baseVersionId": first["id"], "body": "你是一名风格规划专家。",
            "applicability": {"runtimeRole": "style-planner"},
            "outputSchema": {"type": "object", "required": ["stylePrompt"]},
            "inputSchema": [{"name": "structured_input"}],
        })
        assert response.status_code == 201
        second = response.json()["data"]["version"]
        assert second["applicability"] == {"runtimeRole": "style-planner"}
        assert second["outputSchema"] == {"type": "object", "required": ["stylePrompt"]}
        old = (await client.get(f"/api/prompt-versions/{first['id']}")).json()["data"]
        assert old == first
        inherited = await client.post(f"/api/prompt-templates/{template_id}/versions", json={
            "baseVersionId": second["id"], "body": "修改后的风格专家正文",
        })
        assert inherited.json()["data"]["version"]["applicability"] == second["applicability"]


@pytest.mark.asyncio
async def test_style_edit_rejects_planning_template_before_creating_job():
    from backend.tests.test_style_harmonization import fixture
    service, _, project, _, _, old, editor, _ = await fixture()
    _, version = await service.prompts.create_template_with_version(
        code="style-planner", name="风格规划", kind="image_to_image", kind_name="风格规划",
        execution_target="llm", body="你是一名风格规划专家。",
        applicability={"runtimeRole": "style-planner"},
    )
    with pytest.raises(AppError, match="规划") as raised:
        await service.submit(project.id, {
            "assetIds": [str(old.id)], "mode": "prompt", "promptVersionId": str(version.id),
        }, "reject-meta")
    assert raised.value.code == "PROMPT_REQUIRES_PLANNING"
    assert await service.list_jobs(project.id) == []
    assert editor.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["style-planner", "planner"])
async def test_direct_image_test_rejects_meta_prompt_before_record_or_provider(role):
    from backend.app.application.library_services import SqlAlchemyTestRunService
    from backend.app.models.prompt import PromptVersion

    class Session:
        async def get(self, model, _key):
            assert model is PromptVersion
            return SimpleNamespace(applicability={"runtimeRole": role})

        def add(self, _record):
            pytest.fail("planning template must not create a direct image job")

    @asynccontextmanager
    async def sessions():
        yield Session()

    with pytest.raises(AppError) as raised:
        await SqlAlchemyTestRunService(sessions).create_run({
            "promptVersionId": str(uuid4()), "inputText": "商品资料",
        })
    assert raised.value.code == "PROMPT_REQUIRES_PLANNING"
