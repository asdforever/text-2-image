from copy import deepcopy
from io import BytesIO
from uuid import uuid4, UUID

import pytest
import httpx
from PIL import Image

from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage
from backend.app.application.project_asset_service import ProjectAssetService
from backend.app.application.hero_generation_ports import ImageEditResult
from backend.app.core.errors import AppError


def png(color):
    stream = BytesIO()
    Image.new("RGB", (8, 8), color).save(stream, format="PNG")
    return stream.getvalue()


async def fixture():
    from backend.app.canvas_generation_repository import MemoryCanvasGenerationRepository
    from backend.app.application.canvas_generation_service import CanvasGenerationService
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), uuid4(), "owner"))
    projects, storage = InMemoryProjectRepository(), MemoryProjectAssetStorage()
    assets = ProjectAssetService(projects, storage, identity)
    project = await projects.create_project("版本测试", identity.get_context().workspace_id)
    source = await assets.upload_asset(project.id, "source", png("red"), "image/png", "原图.png")
    white = await assets.upload_asset(project.id, "white_background", png("white"), "image/png", "白底.png", source_asset_id=source.id)
    old = await assets.create_generated_asset(project.id, png("green"), "image/png", "原主图.png", source_asset_id=white.id, generation_snapshot_id=uuid4())
    step = {"id": "batch-module:original", "kind": "hero", "title": "细节特写", "sourceAssetIds": [str(white.id)], "outputAssetIds": [str(old.id)], "outputVersionIds": [], "taskPrompt": "旧任务", "finalPrompt": "旧完整提示词", "constraints": {"style": {"content": "固定风格"}, "market": {"content": "固定平台"}}, "parameters": {"aspectRatio": "1:1", "resolution": "2K"}}
    class Editor:
        supports_multiple_source_images = True
        def __init__(self): self.requests, self.fail = [], False
        def describe_request(self, request): return {}
        async def edit(self, request):
            self.requests.append(request)
            if self.fail: raise RuntimeError("secret upstream error")
            return ImageEditResult(png("blue"), "image/png", {})
    class Archive:
        def __init__(self): self.items = []
        async def archive_project_output(self, **item): self.items.append(item)
    async def load_steps(project_id): return [deepcopy(step)] if project_id == project.id else []
    editor, archive, repository = Editor(), Archive(), MemoryCanvasGenerationRepository()
    service = CanvasGenerationService(repository, projects, storage, assets, editor, archive, identity, load_steps, "fake-model")
    return service, project, source, white, old, step, editor, archive


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["hero", "suite"])
async def test_restore_bound_prompts_preview_and_generation_preserve_history(kind):
    from hashlib import sha256
    from backend.app.prompt_repository import MemoryPromptRepository
    service, project, source, white, old, step, editor, archive = await fixture()
    step["kind"] = kind
    prompts = MemoryPromptRepository()
    service.prompt_repository = prompts
    bodies = {"style": "高级棚拍完整正文\n深色无缝背景，100mm 微距镜头，轮廓光，无文字。", "market": "平台完整正文\n主体完整、无水印。"}
    for key, body in bodies.items():
        template, version = await prompts.create_template_with_version(code=key, name=key, kind="generation", kind_name="图片生成", execution_target="image", body=body, user_prompt_template="")
        step["constraints"][key].update(source="style_description" if key == "style" else "market_guidance", promptTemplateId=str(template.id), promptVersionId=str(version.id), promptVersionSha256=version.content_sha256, contentSha256=sha256(step["constraints"][key]["content"].encode()).hexdigest())
    historical = deepcopy(step)
    preview = await service.preview_constraints(project.id, step["id"], "original")
    from backend.app.main import create_app
    from backend.app.core.config import Settings
    app = create_app(settings=Settings(_env_file=None), project_repository=service.projects, identity_provider=service.identity)
    app.state.canvas_generation_service = service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/projects/{project.id}/canvas/constraint-preview", params={"stepId": step["id"], "baseRevisionId": "original"})
        assert response.status_code == 200
        assert response.json()["data"] == preview
        rejected = await client.post(f"/api/projects/{project.id}/canvas/generations", headers={"Idempotency-Key": "invalid-preview"}, json={"stepId": step["id"], "baseRevisionId": "original", "taskPrompt": "任务", "restoredConstraintsHash": "0" * 64})
        assert rejected.status_code == 409
    assert not editor.requests
    assert await service.repository.list(project.id, service.scope) == []
    assert step == historical
    for key, body in bodies.items():
        assert preview["constraints"][key]["content"] == body
        assert preview["constraints"][key]["source"] == "prompt_version_body"
    with pytest.raises(AppError, match="预览已变化"):
        await service.submit(project.id, step["id"], "original", "新任务", None, "bad-hash", "0" * 64)
    revision = await service.submit(project.id, step["id"], "original", "新任务", None, "restore", preview["constraintsHash"])
    replay = await service.submit(project.id, step["id"], "original", "新任务", None, "restore", preview["constraintsHash"])
    assert replay["id"] == revision["id"]
    await service.execute(project.id, step["id"], revision["id"])
    assert len(editor.requests) == 1
    assert editor.requests[0].image_bytes == png("white")
    assert all(body in editor.requests[0].prompt for body in bodies.values())
    track = (await service.list_tracks(project.id))[0]
    assert track["revisions"][0]["constraints"] == historical["constraints"]
    assert track["revisions"][0]["finalPrompt"] == historical["finalPrompt"]
    assert (await service.preview_constraints(project.id, step["id"], "original")) == preview
    assert (await service.preview_constraints(project.id, step["id"], revision["id"])) == preview
    with pytest.raises(AppError):
        await service.preview_constraints(uuid4(), step["id"], "original")
    with pytest.raises(AppError):
        await service.preview_constraints(project.id, step["id"], "missing")
    version.content_sha256 = "changed"
    with pytest.raises(AppError, match="版本内容已改变"):
        await service.preview_constraints(project.id, step["id"], "original")
    prompts.versions.clear()
    with pytest.raises(AppError):
        await service.preview_constraints(project.id, step["id"], "original")


@pytest.mark.asyncio
async def test_regeneration_freezes_upstream_and_constraints_and_persists_version_selection():
    service, project, source, white, old, step, editor, archive = await fixture()
    version = await service.submit(project.id, step["id"], "original", "新的特写任务", None, "same-request")
    replay = await service.submit(project.id, step["id"], "original", "新的特写任务", None, "same-request")
    assert replay["id"] == version["id"]
    step["constraints"]["style"]["content"] = "修改后的目录内容"
    await service.execute(project.id, step["id"], version["id"])
    await service.execute(project.id, step["id"], version["id"])
    assert len(editor.requests) == 1
    assert editor.requests[0].image_bytes == png("white")
    assert "固定风格" in editor.requests[0].prompt
    assert "固定平台" in editor.requests[0].prompt
    assert "新的特写任务" in editor.requests[0].prompt
    assert "修改后的目录内容" not in editor.requests[0].prompt
    track = (await service.list_tracks(project.id))[0]
    assert [v["number"] for v in track["revisions"]] == [1, 2]
    new_id = track["currentAssetIds"][0]
    assert new_id != str(old.id)
    assert archive.items[0]["product_type"] == "hero"
    assert archive.items[0]["source_snapshot"]["batchId"] == version["id"]
    assert archive.items[0]["source_snapshot"]["moduleId"] == "hero"
    result = await service.projects.get_asset(UUID(new_id), service.scope)
    assert result.source_asset_id == white.id
    await service.select(project.id, step["id"], 0, str(old.id))
    assert (await service.list_tracks(project.id))[0]["currentAssetIds"] == [str(old.id)]
    assert (await service.list_tracks(project.id))[0]["revisions"][1]["taskPrompt"] == "新的特写任务"


@pytest.mark.asyncio
async def test_failure_retains_image_and_rejects_wrong_sources_and_reused_key():
    service, project, source, white, old, step, editor, archive = await fixture()
    with pytest.raises(AppError):
        await service.submit(project.id, step["id"], "original", "提示词", [str(old.id)], "wrong-source")
    with pytest.raises(AppError):
        await service.submit(project.id, step["id"], "original", "   ", None, "empty")
    revision = await service.submit(project.id, step["id"], "original", "失败任务", None, "fail")
    with pytest.raises(AppError):
        await service.submit(project.id, step["id"], "original", "不同任务", None, "fail")
    editor.fail = True
    await service.execute(project.id, step["id"], revision["id"])
    track = (await service.list_tracks(project.id))[0]
    assert track["currentAssetIds"] == [str(old.id)]
    assert track["revisions"][-1]["status"] == "failed"
    assert "secret" not in str(track)
    with pytest.raises(AppError):
        await service.select(project.id, step["id"], 0, str(white.id))
    with pytest.raises(AppError):
        await service.submit(uuid4(), step["id"], "original", "任务", None, "foreign")


@pytest.mark.asyncio
async def test_white_background_versions_regenerate_from_original_and_keep_white_asset_kind():
    service, project, source, white, old, step, editor, archive = await fixture()
    step.update(id="edit-version:white", kind="white", sourceAssetIds=[str(source.id)], outputAssetIds=[str(white.id)], constraints={}, taskPrompt="", finalPrompt="旧白底提示词")
    revision = await service.submit(project.id, step["id"], "original", "新白底提示词", None, "white")
    await service.execute(project.id, step["id"], revision["id"])
    assert editor.requests[0].image_bytes == png("red")
    assert editor.requests[0].prompt == "新白底提示词"
    track = (await service.list_tracks(project.id))[0]
    result = await service.projects.get_asset(UUID(track["currentAssetIds"][0]), service.scope)
    assert result.kind == "white_background"
    assert archive.items[0]["product_type"] == "white_background"


@pytest.mark.asyncio
async def test_canvas_routes_submit_once_and_select_only_own_completed_output():
    from backend.app.main import create_app
    from backend.app.core.config import Settings
    service, project, source, white, old, step, editor, archive = await fixture()
    app = create_app(settings=Settings(_env_file=None), project_repository=service.projects, identity_provider=service.identity)
    app.state.canvas_generation_service = service
    payload = {"stepId": step["id"], "baseRevisionId": "original", "taskPrompt": "API 新提示词", "sourceAssetIds": [str(white.id)]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(f"/api/projects/{project.id}/canvas/generations", json=payload, headers={"Idempotency-Key": "api-once"})
        assert first.status_code == 202
        replay = await client.post(f"/api/projects/{project.id}/canvas/generations", json=payload, headers={"Idempotency-Key": "api-once"})
        assert replay.status_code == 202
        assert len(editor.requests) == 1
        workbench = await client.get(f"/api/suites/{project.id}/workbench")
        assert workbench.json()["data"]["generationTracks"][0]["revisions"][-1]["status"] == "succeeded"
        selected = await client.post(f"/api/projects/{project.id}/canvas/version-selection", json={"stepId": step["id"], "outputIndex": 0, "assetId": str(old.id)})
        assert selected.status_code == 200
        foreign = await client.post(f"/api/projects/{uuid4()}/canvas/version-selection", json={"stepId": step["id"], "outputIndex": 0, "assetId": str(old.id)})
        assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_interrupted_provider_keeps_old_image_and_allows_explicit_resubmission():
    import asyncio
    service, project, source, white, old, step, editor, archive = await fixture()
    async def interrupted(request): raise asyncio.CancelledError()
    editor.edit = interrupted
    revision = await service.submit(project.id, step["id"], "original", "中断任务", None, "interrupt")
    with pytest.raises(asyncio.CancelledError):
        await service.execute(project.id, step["id"], revision["id"])
    track = (await service.list_tracks(project.id))[0]
    assert track["revisions"][-1]["status"] == "failed"
    assert track["currentAssetIds"] == [str(old.id)]
    new = await service.submit(project.id, step["id"], revision["id"], "明确重新生成", None, "retry-interrupted")
    assert new["number"] == 3


@pytest.mark.asyncio
async def test_expired_worker_is_marked_failed_without_automatic_generation():
    service, project, source, white, old, step, editor, archive = await fixture()
    revision = await service.submit(project.id, step["id"], "original", "重启任务", None, "restart")
    def expire(state):
        state["revisions"][-1].update(status="generating", leaseExpiresAt="2000-01-01T00:00:00+00:00")
    await service.repository.change(project.id, service.scope, step["id"], None, expire)
    track = (await service.list_tracks(project.id))[0]
    assert track["revisions"][-1]["status"] == "failed"
    assert track["currentAssetIds"] == [str(old.id)]
    await service.execute(project.id, step["id"], revision["id"])
    assert not editor.requests
    retry = await service.submit(project.id, step["id"], revision["id"], "人工重试", None, "restart-explicit")
    assert retry["number"] == 3


@pytest.mark.asyncio
async def test_original_batch_must_finish_before_freezing_output_slots():
    service, project, source, white, old, step, editor, archive = await fixture()
    step["batchStatus"] = "running"
    with pytest.raises(AppError, match="原批次"):
        await service.submit(project.id, step["id"], "original", "迭代任务", None, "early")
    assert await service.list_tracks(project.id) == []


@pytest.mark.asyncio
async def test_multiple_outputs_checkpoint_success_before_interruption_and_keep_slot_identity():
    import asyncio
    service, project, source, white, old, step, editor, archive = await fixture()
    second = await service.assets.create_generated_asset(project.id, png("yellow"), "image/png", "第二张.png", source_asset_id=white.id, generation_snapshot_id=uuid4())
    step["outputAssetIds"].append(str(second.id))
    original_edit = editor.edit
    async def interrupt_second(request):
        if editor.requests:
            persisted = (await service.list_tracks(project.id))[0]
            assert len(persisted["revisions"][-1]["outputs"]) == 1
            raise asyncio.CancelledError()
        return await original_edit(request)
    editor.edit = interrupt_second
    revision = await service.submit(project.id, step["id"], "original", "多图任务", None, "multi")
    with pytest.raises(asyncio.CancelledError):
        await service.execute(project.id, step["id"], revision["id"])
    track = (await service.list_tracks(project.id))[0]
    assert track["revisions"][-1]["status"] == "partial"
    assert track["currentAssetIds"][0] != str(old.id)
    assert track["currentAssetIds"][1] == str(second.id)
    with pytest.raises(AppError):
        await service.select(project.id, step["id"], 1, track["currentAssetIds"][0])


@pytest.mark.asyncio
async def test_explicit_upstream_version_and_duplicate_worker_claim():
    import asyncio
    service, project, source, white, old, step, editor, archive = await fixture()
    hero = deepcopy(step)
    step.update(id="white-step", kind="white", sourceAssetIds=[str(source.id)], outputAssetIds=[str(white.id)], constraints={})
    white_revision = await service.submit(project.id, step["id"], "original", "新白底", None, "white-new")
    await service.execute(project.id, step["id"], white_revision["id"])
    new_white = (await service.list_tracks(project.id))[0]["currentAssetIds"][0]
    step.update(hero)
    revision = await service.submit(project.id, step["id"], "original", "沿用新白底", [new_white], "hero-new")
    assert revision["sourceAssetIds"] == [new_white]
    await asyncio.gather(service.execute(project.id, step["id"], revision["id"]), service.execute(project.id, step["id"], revision["id"]))
    assert len(editor.requests) == 2
    assert editor.requests[-1].image_bytes == png("blue")
