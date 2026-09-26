from uuid import uuid4

import httpx
import pytest

from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.core.config import Settings
from backend.app.image_editing_repository import ImageEditVersionRecord, InMemoryImageEditingRepository
from backend.app.application.image_editing_service import ImageEditingService
from backend.app.main import create_app
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.workbench_repository import InMemoryWorkbenchRepository
from backend.app.batch_generation_repository import InMemoryBatchGenerationRepository, ConfirmedGenerationModuleInput


@pytest.mark.asyncio
async def test_canvas_returns_project_scoped_edit_results_and_versions():
    workspace_id = uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    projects = InMemoryProjectRepository()
    repository = InMemoryImageEditingRepository()
    service = ImageEditingService(repository, projects, identity)
    project = await projects.create_project("画布项目", workspace_id)
    other = await projects.create_project("另一项目", workspace_id)
    obj = await projects.create_object(workspace_id, "image.png", "image.png", "image/png", 10, 800, 600, "a" * 64)
    source = await projects.create_asset(project.id, obj.id, "source")
    other_source = await projects.create_asset(other.id, obj.id, "source")
    session = await service.create_session(project.id, source.id)
    task = await service.submit_session(session.id, prompt_snapshot={"summary": "调整背景"}, config_snapshot={"sourceCardId": "asset:original", "outputKind": "white_background"})
    foreign_session = await service.create_session(other.id, other_source.id)
    await service.submit_session(foreign_session.id, prompt_snapshot={"summary": "不应出现"}, config_snapshot={})
    version = ImageEditVersionRecord(uuid4(), task.id, task.attempts[0].id, 1, "edited.png", "/edited.png", source_snapshot={"width": 800, "height": 600})
    await repository.add_version(task.id, version)
    white = await projects.create_asset(project.id, obj.id, "white_background", source_asset_id=source.id, source_kind="generated", source_snapshot={"imageEditTaskId": str(task.id)})
    app = create_app(settings=Settings(_env_file=None), identity_provider=identity, project_repository=projects, workbench_repository=InMemoryWorkbenchRepository(), image_editing_service=service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/suites/{project.id}/workbench")
    assert response.status_code == 200
    children = response.json()["data"]["imageEditChildren"]
    assert len(children) == 1
    assert children[0]["task"]["id"] == str(task.id)
    assert children[0]["task"]["summary"] == "调整背景"
    assert children[0]["versions"][0]["previewUrl"] == "/edited.png"
    assert children[0]["versions"][0]["width"] == 800
    steps = response.json()["data"]["generationSteps"]
    assert steps[0]["kind"] == "white"
    assert steps[0]["outputAssetIds"] == [str(white.id)]
    assert steps[0]["sourceAssetIds"] == [str(source.id)]
    version.preview_url = "https://storage.example/expired-signature"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        refreshed = await client.get(f"/api/suites/{project.id}/workbench")
    assert refreshed.json()["data"]["imageEditChildren"][0]["versions"][0]["previewUrl"] == "/api/storage/edited.png"


@pytest.mark.asyncio
async def test_editor_submit_dispatches_only_the_new_queued_attempt():
    workspace_id = uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    projects = InMemoryProjectRepository()
    project = await projects.create_project("编辑项目", workspace_id)
    obj = await projects.create_object(workspace_id, "a.png", "a.png", "image/png", 10, 8, 8, "b" * 64)
    asset = await projects.create_asset(project.id, obj.id, "source")
    service = ImageEditingService(None, projects, identity)
    session = await service.create_session(project.id, asset.id)
    app = create_app(settings=Settings(_env_file=None), identity_provider=identity, project_repository=projects, image_editing_service=service)
    dispatched = []

    class Worker:
        async def process_task(self, task_id):
            task = await service.repository.get_task(task_id, workspace_id)
            dispatched.append(task_id)
            await service.repository.complete_attempt(task_id, task.attempts[-1].id, success=True)

    app.state.image_editing_worker = Worker()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        payload = {"promptSnapshot": {"summary": "把背景改为暖灰色"}, "configSnapshot": {"outputKind": "canvas_edit"}}
        first = await client.post(f"/api/image-editor/sessions/{session.id}/submit", json=payload, headers={"Idempotency-Key": "same-edit"})
        assert first.status_code == 202
        replay = await client.post(f"/api/image-editor/sessions/{session.id}/submit", json=payload, headers={"Idempotency-Key": "same-edit"})
        assert replay.status_code == 202
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_canvas_lineage_uses_batch_snapshot_without_legacy_tasks_and_rejects_foreign_batch():
    workspace_id = uuid4()
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), workspace_id, "owner"))
    projects = InMemoryProjectRepository()
    batches = InMemoryBatchGenerationRepository()
    project = await projects.create_project("生成脉络", workspace_id)
    obj = await projects.create_object(workspace_id, "a.png", "a.png", "image/png", 10, 8, 8, "b" * 64)
    source = await projects.create_asset(project.id, obj.id, "source")
    snapshot = {"selection": {"module": {"name": "场景主图", "mode": "hero"}, "aspectRatio": "1:1", "resolution": "2K"}, "constraints": {"style": {"content": "历史风格"}, "market": {"content": "历史平台"}}}
    batch, _ = await batches.create_confirmed_from_plan(workspace_id, project.id, uuid4(), source.id, "one", "a" * 64, {"sourceAssets": [{"assetId": str(source.id)}]}, [ConfirmedGenerationModuleInput("scene", 1, 2, snapshot, "编译", {}, "确认提示词", "完整历史提示词", "b" * 64)])
    detail = await batches.get_batch_detail(batch.id, workspace_id)
    outputs = [await projects.create_asset(project.id, obj.id, "generated", source_asset_id=source.id, generation_snapshot_id=slot.id) for slot in detail.slots]
    foreign, _ = await batches.create_confirmed_from_plan(uuid4(), uuid4(), uuid4(), source.id, "foreign", "c" * 64, {}, [ConfirmedGenerationModuleInput("x", 1, 1, {}, "秘密", {}, "秘密", "秘密", "d" * 64)])
    foreign_detail = await batches.get_batch_detail(foreign.id, foreign.workspace_id)
    await projects.create_asset(project.id, obj.id, "generated", generation_snapshot_id=foreign_detail.slots[0].id)
    app = create_app(settings=Settings(_env_file=None), identity_provider=identity, project_repository=projects, batch_generation_repository=batches, workbench_repository=InMemoryWorkbenchRepository())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/suites/{project.id}/workbench")
    assert response.status_code == 200
    steps = response.json()["data"].get("generationSteps", [])
    assert len(steps) == 1
    assert steps[0]["sourceAssetIds"] == [str(source.id)]
    assert set(steps[0]["outputAssetIds"]) == {str(a.id) for a in outputs}
    assert steps[0]["finalPrompt"] == "完整历史提示词"
    assert steps[0]["constraints"]["style"]["content"] == "历史风格"
    assert steps[0]["parameters"]["resolution"] == "2K"
