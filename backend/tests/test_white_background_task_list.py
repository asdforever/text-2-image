import httpx
import pytest

from backend.app.application.image_editing_service import ImageEditingService
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.tests.test_canvas_generation import fixture


@pytest.mark.asyncio
async def test_list_white_background_tasks_recovers_only_project_scoped_white_jobs_without_generation():
    canvas, project, source, _, _, _, editor, _ = await fixture()
    service = ImageEditingService(None, canvas.projects, canvas.identity)
    session = await service.create_session(project.id, source.id)
    white = await service.submit_session(session.id, prompt_snapshot={"summary": "白底图"}, config_snapshot={"outputKind": "white_background"}, idempotency_key="white")
    await service.submit_session(session.id, prompt_snapshot={"summary": "普通编辑"}, config_snapshot={"outputKind": "canvas_edit"}, idempotency_key="edit")
    other = await canvas.projects.create_project("其他项目", canvas.scope)
    app = create_app(settings=Settings(_env_file=None), project_repository=canvas.projects, identity_provider=canvas.identity)
    app.state.image_editing_service = service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/projects/{project.id}/white-background-generations")
        assert response.status_code == 200
        tasks = response.json()["data"]
        assert [t["id"] for t in tasks] == [str(white.id)]
        assert tasks[0]["status"] == "queued"
        assert tasks[0]["sourceSnapshot"]["assetId"] == str(source.id)
        assert (await client.get(f"/api/projects/{other.id}/white-background-generations")).json()["data"] == []
        assert not editor.requests
