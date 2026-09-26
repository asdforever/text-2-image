from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.prompt_repository import MemoryPromptRepository
from backend.app.core.errors import AppError
from backend.tests.test_hero_generation_compile_service import _fixture, _input


async def version_in(repository, role):
    return await repository.create_template_with_version(
        code=f"boundary-{uuid4()}", name="白底图模板", kind="image_to_image", kind_name="图片编辑",
        execution_target="image_model", body="保留真实商品并换为纯白背景。",
        applicability={"runtimeRole": role} if role else {},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["style-planner", "planner", "hero-module-planner", "suite-module-planner"])
@pytest.mark.parametrize("entry", ["white", "edit"])
async def test_direct_image_routes_reject_planners_before_creating_session_or_task(role, entry):
    prompts = MemoryPromptRepository()
    template, version = await version_in(prompts, role)
    service = SimpleNamespace(create_session=AsyncMock(), submit_session=AsyncMock())
    app = create_app(Settings(_env_file=None, database_url=None, pg_host=None), prompt_repository=prompts, image_editing_service=service)
    payload = {"promptBody": "看似普通的客户端文本", "promptTemplateId": str(template.id), "promptVersionId": str(version.id)}
    path = f"/api/projects/{uuid4()}/assets/{uuid4()}/white-background-generations"
    if entry == "edit":
        path = f"/api/image-editor/sessions/{uuid4()}/submit"
        payload = {"promptSnapshot": {"summary": "编辑", "promptVersionId": str(version.id)}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PROMPT_REQUIRES_PLANNING"
    service.create_session.assert_not_awaited()
    service.submit_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["malformed", "missing", "mismatched"])
async def test_white_background_rejects_invalid_template_reference_before_session(invalid):
    prompts = MemoryPromptRepository()
    template, version = await version_in(prompts, None)
    service = SimpleNamespace(create_session=AsyncMock())
    app = create_app(Settings(_env_file=None, database_url=None, pg_host=None), prompt_repository=prompts, image_editing_service=service)
    payload = {"promptBody": "纯白背景", "promptTemplateId": str(template.id), "promptVersionId": str(version.id)}
    if invalid == "malformed":
        payload["promptVersionId"] = "not-a-uuid"
    elif invalid == "missing":
        payload["promptVersionId"] = str(uuid4())
    else:
        payload["promptTemplateId"] = str(uuid4())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/projects/{uuid4()}/assets/{uuid4()}/white-background-generations", json=payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IMAGE_PROMPT_VERSION_INVALID"
    service.create_session.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["style-planner", "planner", "hero-module-planner", "suite-module-planner"])
async def test_market_binding_cannot_inject_planning_instructions_into_final_prompt(role):
    fixture = await _fixture()
    template, version = await version_in(fixture.prompts, role)
    published = await fixture.config.get_published()
    config = published.content
    config["marketBindings"]["taobao"] = {"promptTemplateId": str(template.id), "promptVersionId": str(version.id)}
    fixture.config.get_published = AsyncMock(return_value=SimpleNamespace(content=config, version_no=1, content_sha256="a" * 64))
    with pytest.raises(AppError) as exc:
        await fixture.service.compile_prompt(fixture.project_id, _input(fixture.source_asset_id), "market-planner")
    assert exc.value.code == "PROMPT_REQUIRES_PLANNING"
    assert not fixture.compiler.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["white", "custom-edit"])
async def test_legacy_white_prompt_and_custom_edit_remain_usable(entry):
    from backend.app.application.image_editing_service import ImageEditingService
    from backend.tests.test_canvas_generation import fixture as canvas_fixture
    canvas, project, source, _, _, _, _, _ = await canvas_fixture()
    service = ImageEditingService(None, canvas.projects, canvas.identity)
    prompts = MemoryPromptRepository()
    template, version = await version_in(prompts, None)
    app = create_app(Settings(_env_file=None, database_url=None, pg_host=None),
        project_repository=canvas.projects, identity_provider=canvas.identity,
        prompt_repository=prompts, image_editing_service=service)
    app.state.image_editing_worker = SimpleNamespace(process_task=AsyncMock())
    if entry == "white":
        path = f"/api/projects/{project.id}/assets/{source.id}/white-background-generations"
        payload = {"promptBody": "历史白底正文", "promptTemplateId": str(template.id), "promptVersionId": str(version.id)}
        expected = "历史白底正文"
    else:
        session = await service.create_session(project.id, source.id)
        path = f"/api/image-editor/sessions/{session.id}/submit"
        payload = {"summary": "用户自定义编辑文本"}
        expected = "用户自定义编辑文本"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json=payload)
    assert response.status_code == 202
    assert response.json()["data"]["promptSnapshot"]["summary"] == expected
