from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from backend.app.application.image_editing_service import ImageEditingService
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.prompt_repository import MemoryPromptRepository
from backend.tests.test_canvas_generation import fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("background,code,label", [("white", "product-white", "白底图"), ("transparent", "product-transparent", "透明图")])
async def test_background_generation_binds_marketplace_default_and_ignores_client_prompt(background, code, label):
    canvas, project, source, *_ = await fixture()
    prompts = MemoryPromptRepository()
    template, version = await prompts.create_template_with_version(code=code, name=f"商品{label}生成", kind="image_to_image", kind_name="商品图", execution_target="image_model", body=f"保持商品，生成{label}")
    service = ImageEditingService(None, canvas.projects, canvas.identity)
    app = create_app(Settings(_env_file=None, database_url=None, pg_host=None), project_repository=canvas.projects, identity_provider=canvas.identity, prompt_repository=prompts, image_editing_service=service)
    app.state.image_editing_worker = SimpleNamespace(process_task=AsyncMock())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/projects/{project.id}/assets/{source.id}/white-background-generations", json={"background": background, "promptBody": "错误的 eBay 提示词", "promptTemplateId": str(uuid4()), "promptVersionId": str(uuid4())})
    assert response.status_code == 202, response.text
    task = response.json()["data"]
    assert task["promptSnapshot"]["summary"] == version.body
    assert task["promptSnapshot"]["promptTemplateId"] == str(template.id)
    assert task["promptSnapshot"]["promptVersionId"] == str(version.id)
    assert task["configSnapshot"]["background"] == background
    assert label in task["configSnapshot"]["outputFilename"]


@pytest.mark.asyncio
async def test_missing_bound_prompt_does_not_fall_back_to_marketplace_first():
    service = SimpleNamespace(create_session=AsyncMock())
    app = create_app(Settings(_env_file=None, database_url=None, pg_host=None), prompt_repository=MemoryPromptRepository(), image_editing_service=service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/projects/{uuid4()}/assets/{uuid4()}/white-background-generations", json={"background": "transparent"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PRODUCT_BACKGROUND_PROMPT_UNAVAILABLE"
    service.create_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("background", ["blue", [], None])
async def test_invalid_background_is_rejected_before_creating_session(background):
    service = SimpleNamespace(create_session=AsyncMock())
    app = create_app(Settings(_env_file=None, database_url=None, pg_host=None), image_editing_service=service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/projects/{uuid4()}/assets/{uuid4()}/white-background-generations", json={"background": background})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PRODUCT_BACKGROUND_INVALID"
    service.create_session.assert_not_awaited()
