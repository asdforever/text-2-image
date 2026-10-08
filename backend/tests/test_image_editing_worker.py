from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image

from backend.app.application.image_editing_service import ImageEditingService
from backend.app.application.image_editing_worker import ImageEditingWorker
from backend.app.application.project_asset_service import ProjectAssetService
from backend.app.application.hero_generation_ports import ImageEditResult
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage
from backend.app.storage import StoredObject


def _png(color="red"):
    out = BytesIO(); Image.new("RGB", (8, 8), color).save(out, format="PNG"); return out.getvalue()


class FakeEditor:
    def __init__(self, fail=False): self.fail, self.calls, self.requests = fail, 0, []
    def describe_request(self, request): return {"prompt": request.prompt}
    async def edit(self, request):
        self.calls += 1
        self.requests.append(request)
        if self.fail: raise RuntimeError("provider down")
        return ImageEditResult(_png("blue"), "image/png", {"model": "fake"})


class RecordingArchive:
    def __init__(self): self.calls = []
    async def archive_project_output(self, **payload): self.calls.append(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_alpha", [True, False])
@pytest.mark.parametrize("opacity", [255, 128])
async def test_transparent_output_keeps_alpha_and_rejects_opaque_results(valid_alpha, opacity):
    workspace_id = UUID(int=66)
    identity = LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner"))
    projects = InMemoryProjectRepository()
    project = await projects.create_project("透明图项目", workspace_id)
    storage = MemoryProjectAssetStorage()
    assets = ProjectAssetService(projects, storage, identity)
    source = await assets.upload_asset(project.id, "source", _png(), "image/png", "原图.png")
    service = ImageEditingService(None, projects, identity)
    session = await service.create_session(project.id, source.id)
    task = await service.submit_session(session.id, prompt_snapshot={"summary": "保留产品，透明背景"}, config_snapshot={"outputKind": "white_background", "background": "transparent", "outputFilename": "透明图.png"})
    image = Image.new("RGBA", (8, 8), (255, 255, 255, 0))
    image.paste((255, 0, 0, opacity), (2, 2, 6, 6))
    output = BytesIO()
    (image if valid_alpha else image.convert("RGB")).save(output, format="PNG")
    editor = FakeEditor()
    async def edit(request):
        editor.requests.append(request)
        return ImageEditResult(output.getvalue(), "image/png", {})
    editor.edit = edit
    await ImageEditingWorker(service.repository, projects, storage, service, editor, assets).process_task(task.id)
    assert editor.requests[0].background == "transparent"
    results = [asset for asset in await assets.list_assets(project.id) if asset.kind == "white_background"]
    if valid_alpha:
        assert task.status == "succeeded"
        assert results[0].source_snapshot["background"] == "transparent"
        obj = await projects.get_object(results[0].object_id, workspace_id)
        stored = await storage.get(obj.storage_key)
        assert Image.open(BytesIO(stored.data)).getchannel("A").getextrema() == (0, opacity)
    else:
        assert task.status == "failed"
        assert "透明" in task.attempts[-1].error_message
        assert not task.versions and not results


@pytest.mark.asyncio
async def test_canvas_edit_passes_the_real_instruction_and_archives_the_result_as_project_asset():
    workspace_id = UUID(int=65)
    identity = LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner"))
    projects = InMemoryProjectRepository()
    project = await projects.create_project("画布", workspace_id)
    storage = MemoryProjectAssetStorage()
    assets = ProjectAssetService(projects, storage, identity)
    source = await assets.upload_asset(project.id, "source", _png(), "image/png", "原图.png")
    service = ImageEditingService(None, projects, identity)
    session = await service.create_session(project.id, source.id)
    await service.add_operation(session.id, {"operationId": "edit", "type": "re_edit", "payload": {"prompt": "将背景变成浅灰色，保持商品不变"}}, expected_revision=1)
    task = await service.submit_session(session.id, prompt_snapshot={"summary": "重新编辑提示词"}, config_snapshot={"outputKind": "canvas_edit"})
    editor, archive = FakeEditor(), RecordingArchive()
    worker = ImageEditingWorker(service.repository, projects, storage, service, editor, assets, archive)
    await worker.process_task(task.id)
    await worker.process_task(task.id)
    assert editor.calls == 1
    assert editor.requests[0].prompt == "将背景变成浅灰色，保持商品不变"
    results = [asset for asset in await assets.list_assets(project.id) if asset.kind == "generated"]
    assert len(results) == 1
    assert task.versions[0].preview_url == f"/api/projects/{project.id}/assets/{results[0].id}/preview"
    assert archive.calls[0]["product_type"] == "edit"


@pytest.mark.asyncio
async def test_image_edit_worker_writes_successful_version_and_failed_attempt():
    workspace_id = UUID(int=61)
    projects = InMemoryProjectRepository(); project = await projects.create_project("项目", workspace_id)
    storage = MemoryProjectAssetStorage()
    source_obj = await projects.create_object(workspace_id, "source.png", "source.png", "image/png", len(_png()), 8, 8, "2" * 64)
    await storage.put(StoredObject("source.png", _png(), "image/png"))
    source = await projects.create_asset(project.id, source_obj.id, "source")
    service = ImageEditingService(None, projects, LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")))
    session = await service.create_session(project.id, source.id)
    await service.add_operation(session.id, {"operationId": "op", "type": "erase", "payload": {}}, expected_revision=1)
    task = await service.submit_session(session.id, prompt_snapshot={"summary": "清除"}, config_snapshot={"ratio": "1:1"})
    worker = ImageEditingWorker(service.repository, projects, storage, service, FakeEditor())
    completed = await worker.process_task(task.id)
    assert completed.status == "succeeded"
    assert completed.attempts[0].status == "succeeded"
    assert len(completed.versions) == 1

    failed_task = await service.submit_session(session.id, prompt_snapshot={"summary": "再次"}, config_snapshot={"ratio": "1:1"})
    failed = await ImageEditingWorker(service.repository, projects, storage, service, FakeEditor(fail=True)).process_task(failed_task.id)
    assert failed.status == "failed"
    assert failed.attempts[0].error_message == "provider down"


@pytest.mark.asyncio
async def test_white_background_task_creates_a_project_white_background_asset():
    """白底图任务完成后必须能在项目资产列表中直接使用结果。"""
    workspace_id = UUID(int=64)
    identity = LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner"))
    projects = InMemoryProjectRepository()
    project = await projects.create_project("白底图项目", workspace_id)
    storage = MemoryProjectAssetStorage()
    source_object = await projects.create_object(
        workspace_id, "source.png", "source.png", "image/png", len(_png()), 8, 8, "6" * 64
    )
    await storage.put(StoredObject("source.png", _png(), "image/png"))
    source = await projects.create_asset(project.id, source_object.id, "source")
    assets = ProjectAssetService(projects, storage, identity)
    service = ImageEditingService(None, projects, identity)
    session = await service.create_session(project.id, source.id)
    task = await service.submit_session(
        session.id,
        prompt_snapshot={"summary": "保留商品主体，生成纯白背景商品图"},
        config_snapshot={"outputKind": "white_background", "outputFilename": "source-白底图.png"},
    )

    editor = FakeEditor()
    archive = RecordingArchive()
    await ImageEditingWorker(service.repository, projects, storage, service, editor, assets, archive).process_task(task.id)

    generated = [item for item in await assets.list_assets(project.id) if item.kind == "white_background"]
    assert len(generated) == 1
    assert generated[0].source_asset_id == source.id
    assert generated[0].source_kind == "generated"
    assert editor.requests[0].aspect_ratio == "1:1"
    assert editor.requests[0].resolution == "标准 1K"
    assert archive.calls[0]["product_type"] == "white_background"
    assert archive.calls[0]["project_id"] == project.id
    assert archive.calls[0]["source_version_id"] == generated[0].id


@pytest.mark.asyncio
async def test_retry_failed_attempt_and_regenerate_create_new_attempts_without_overwriting_history():
    workspace_id = UUID(int=62)
    projects = InMemoryProjectRepository(); project = await projects.create_project("项目", workspace_id)
    source_obj = await projects.create_object(workspace_id, "source.png", "source.png", "image/png", len(_png()), 8, 8, "3" * 64)
    source = await projects.create_asset(project.id, source_obj.id, "source")
    storage = MemoryProjectAssetStorage(); await storage.put(StoredObject("source.png", _png(), "image/png"))
    service = ImageEditingService(None, projects, LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")))
    session = await service.create_session(project.id, source.id)
    await service.add_operation(session.id, {"operationId": "op", "type": "erase", "payload": {}}, expected_revision=1)
    task = await service.submit_session(session.id, prompt_snapshot={"summary": "清除"}, config_snapshot={})
    failed = await ImageEditingWorker(service.repository, projects, storage, service, FakeEditor(fail=True)).process_task(task.id)
    retried = await service.retry_attempt(failed.attempts[0].id)
    assert len(retried.attempts) == 2
    assert retried.attempts[0].status == "failed" and retried.attempts[1].status == "queued"
    regenerated = await service.regenerate_task(task.id, "换一个背景")
    assert regenerated.id != task.id
    assert regenerated.attempts[0].status == "queued"
    assert len(task.attempts) == 2


@pytest.mark.asyncio
async def test_select_image_edit_version_rejects_incomplete_and_updates_single_pointer():
    workspace_id = UUID(int=63)
    projects = InMemoryProjectRepository(); project = await projects.create_project("项目", workspace_id)
    source_obj = await projects.create_object(workspace_id, "source.png", "source.png", "image/png", len(_png()), 8, 8, "4" * 64)
    source = await projects.create_asset(project.id, source_obj.id, "source")
    storage = MemoryProjectAssetStorage(); await storage.put(StoredObject("source.png", _png(), "image/png"))
    service = ImageEditingService(None, projects, LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner")))
    session = await service.create_session(project.id, source.id)
    await service.add_operation(session.id, {"operationId": "op", "type": "erase", "payload": {}}, expected_revision=1)
    task = await service.submit_session(session.id, prompt_snapshot={"summary": "清除"}, config_snapshot={})
    await ImageEditingWorker(service.repository, projects, storage, service, FakeEditor()).process_task(task.id)
    version = task.versions[0]
    selected = await service.select_version(task.id, version.id, "final")
    assert selected.is_final is True
    assert task.final_version_id == version.id


@pytest.mark.asyncio
async def test_modern_crop_creates_asset_without_model_configuration_or_generation():
    workspace_id = UUID(int=66)
    identity = LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), workspace_id, "owner"))
    projects = InMemoryProjectRepository()
    project = await projects.create_project("裁剪", workspace_id)
    storage = MemoryProjectAssetStorage()
    assets = ProjectAssetService(projects, storage, identity)
    source = await assets.upload_asset(project.id, "source", _png(), "image/png", "原图.png")
    class NoModel:
        async def snapshot(self, model): raise AssertionError("裁剪不能要求配置模型")
    service = ImageEditingService(None, projects, identity, model_connections=NoModel())
    session = await service.create_session(project.id, source.id)
    await service.add_operation(session.id, {"operationId": "crop", "type": "crop_resize", "payload": {"schemaVersion": 2, "region": {"x": .25, "y": 0, "width": .5, "height": 1}, "width": 4, "height": 8}}, expected_revision=1)
    task = await service.submit_session(session.id, prompt_snapshot={"summary": "裁剪"}, config_snapshot={"outputKind": "canvas_edit"})
    editor, archive = FakeEditor(), RecordingArchive()
    await ImageEditingWorker(service.repository, projects, storage, service, editor, assets, archive).process_task(task.id)
    assert task.status == "succeeded"
    assert editor.calls == 0
    assert task.versions[0].source_snapshot["width"] == 4
    assert task.versions[0].source_snapshot["height"] == 8
    generated = [item for item in await assets.list_assets(project.id) if item.kind == "generated"]
    assert len(generated) == 1
    output = await projects.get_object(generated[0].object_id, workspace_id)
    assert (output.width, output.height) == (4, 8)
    assert archive.calls[0]["product_type"] == "edit"


@pytest.mark.asyncio
async def test_canvas_text_without_generation_params_uses_source_portrait_ratio():
    identity = LocalSingleUserIdentityProvider(IdentityContext(UUID(int=1), UUID(int=67), "owner"))
    projects = InMemoryProjectRepository()
    project = await projects.create_project("竖版素材加字", UUID(int=67))
    storage = MemoryProjectAssetStorage()
    assets = ProjectAssetService(projects, storage, identity)
    data = BytesIO(); Image.new("RGB", (60, 80), "white").save(data, format="PNG")
    source = await assets.upload_asset(project.id, "source", data.getvalue(), "image/png", "原图.png")
    service = ImageEditingService(None, projects, identity)
    session = await service.create_session(project.id, source.id)
    await service.add_operation(session.id, {"operationId": "text", "type": "add_text", "payload": {"schemaVersion": 2, "text": "好吃不贵", "region": {"x": .1, "y": .1, "width": .5, "height": .1}}}, expected_revision=1)
    task = await service.submit_session(session.id, prompt_snapshot={"summary": "加字"}, config_snapshot={"outputKind": "canvas_edit", "generationParams": {}})
    editor = FakeEditor()
    await ImageEditingWorker(service.repository, projects, storage, service, editor, assets).process_task(task.id)
    assert task.status == "succeeded"
    assert editor.requests[0].aspect_ratio == "3:4"
