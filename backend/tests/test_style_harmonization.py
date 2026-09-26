from uuid import UUID, uuid4

import httpx
import pytest

from backend.app.core.errors import AppError
from backend.tests.test_canvas_generation import fixture as canvas_fixture, png


async def fixture():
    from backend.app.application.style_harmonization_service import StyleHarmonizationService
    from backend.app.prompt_repository import MemoryPromptRepository
    canvas, project, source, white, old, step, editor, archive = await canvas_fixture()
    service = StyleHarmonizationService(canvas.repository, canvas.projects, canvas.storage,
        canvas.assets, editor, archive, canvas.identity, "fake-model", MemoryPromptRepository())
    await canvas.assets.select_asset(project.id, "generated", old.id)
    return service, canvas, project, source, white, old, editor, archive


@pytest.mark.asyncio
async def test_selected_only_candidates_keep_original_selection_and_archive_full_prompt():
    service, canvas, project, source, white, old, editor, archive = await fixture()
    prompt = "  暖色自然光\n保留标题及商品细节，不删减此完整句。  "
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": prompt}, "one")
    assert not editor.requests
    await service.execute(project.id, job["id"])
    await service.execute(project.id, job["id"])
    saved = (await service.list_jobs(project.id))[0]
    assert saved["status"] == "succeeded"
    assert len(saved["tasks"]) == len(editor.requests) == 1
    assert saved["promptSnapshot"]["content"] == prompt
    assert prompt in editor.requests[0].prompt
    assert "保留" in saved["finalPrompt"]
    assert editor.requests[0].image_bytes == png("green")
    output = await service.projects.get_asset(UUID(saved["tasks"][0]["outputAssetId"]), service.scope)
    assert output.id != old.id and output.source_asset_id == old.id
    assert await service.assets.get_selections(project.id) == {"generated": old.id}
    assert (await service.projects.get_asset(old.id, service.scope)).state == "available"
    assert archive.items[0]["prompt_snapshot"]["finalPrompt"] == saved["finalPrompt"]
    assert await canvas.list_tracks(project.id) == []


@pytest.mark.asyncio
async def test_reference_inputs_frozen_source_first_and_reference_second():
    service, _, project, source, white, old, editor, _ = await fixture()
    job = await service.submit(project.id, {"assetIds": [str(old.id), str(white.id)], "mode": "reference", "referenceAssetId": str(source.id)}, "reference")
    assert job["referenceAsset"]["assetId"] == str(source.id)
    await service.execute(project.id, job["id"])
    assert [[i.image_bytes for i in r.ordered_image_inputs()] for r in editor.requests] == [[png("green"), png("red")], [png("white"), png("red")]]


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime,expected", [("完整运行时正文\n材质与光照", "完整运行时正文\n材质与光照"), ("", "完整版本正文\n不能只使用名字")])
async def test_prompt_version_priority_and_snapshot_survive_version_change(runtime, expected):
    service, _, project, _, _, old, editor, _ = await fixture()
    _, version = await service.prompts.create_template_with_version(code="style", name="短名称", kind="generation", kind_name="风格", execution_target="image", body="完整版本正文\n不能只使用名字", user_prompt_template=runtime)
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "prompt", "promptVersionId": str(version.id)}, "prompt")
    version.body = version.user_prompt_template = "后续改动"
    await service.execute(project.id, job["id"])
    assert expected in editor.requests[0].prompt
    assert "后续改动" not in editor.requests[0].prompt
    assert job["promptSnapshot"]["promptVersionId"] == str(version.id)


@pytest.mark.asyncio
async def test_replay_conflict_failure_and_no_automatic_retry():
    import asyncio
    service, _, project, _, _, old, editor, _ = await fixture()
    payload = {"assetIds": [str(old.id)], "mode": "custom", "prompt": "完整风格"}
    first, replay = await asyncio.gather(service.submit(project.id, payload, "same"), service.submit(project.id, payload, "same"))
    assert first["id"] == replay["id"]
    with pytest.raises(AppError):
        await service.submit(project.id, payload | {"prompt": "不同"}, "same")
    editor.fail = True
    await asyncio.gather(service.execute(project.id, first["id"]), service.execute(project.id, first["id"]))
    await service.execute(project.id, first["id"])
    saved = (await service.list_jobs(project.id))[0]
    assert saved["status"] == "failed"
    assert len(editor.requests) == 1
    assert "secret" not in str(saved)
    assert await service.submit(project.id, payload, "same") == saved


@pytest.mark.asyncio
async def test_invalid_selection_ownership_reference_and_capability_rejected_before_provider():
    service, _, project, _, _, old, editor, _ = await fixture()
    other = await service.projects.create_project("其他项目", service.scope)
    foreign = await service.assets.upload_asset(other.id, "source", png("black"), "image/png", "foreign.png")
    valid = {"assetIds": [str(old.id)], "mode": "custom", "prompt": "风格"}
    invalid = [valid | {"assetIds": []}, valid | {"assetIds": [str(old.id)] * 2}, valid | {"assetIds": [str(uuid4())]}, valid | {"assetIds": [str(foreign.id)]}, valid | {"assetIds": [str(uuid4()) for _ in range(21)]}, valid | {"mode": "reference", "referenceAssetId": str(foreign.id)}, valid | {"mode": "reference", "referenceAssetId": str(uuid4())}, valid | {"mode": "prompt", "promptVersionId": str(uuid4())}]
    for index, payload in enumerate(invalid):
        with pytest.raises(AppError):
            await service.submit(project.id, payload, str(index))
    editor.supports_multiple_source_images = False
    with pytest.raises(AppError):
        await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "reference", "referenceAssetId": str(old.id)}, "unsupported")
    assert await service.list_jobs(project.id) == []
    assert not editor.requests


@pytest.mark.asyncio
async def test_frozen_reference_content_change_fails_without_generation():
    service, _, project, source, _, old, editor, _ = await fixture()
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "reference", "referenceAssetId": str(source.id)}, "freeze")
    obj = await service.projects.get_object(source.object_id, service.scope)
    obj.sha256 = "changed"
    await service.execute(project.id, job["id"])
    assert (await service.list_jobs(project.id))[0]["status"] == "failed"
    assert not editor.requests


@pytest.mark.asyncio
async def test_routes_require_key_return_chinese_validation_and_replay_without_provider_call():
    from backend.app.main import create_app
    from backend.app.core.config import Settings
    service, _, project, _, _, old, editor, _ = await fixture()
    app = create_app(settings=Settings(_env_file=None), project_repository=service.projects, identity_provider=service.identity)
    app.state.style_harmonization_service = service
    url = f"/api/projects/{project.id}/style-harmonizations"
    payload = {"assetIds": [str(old.id)], "mode": "custom", "prompt": "API 风格"}
    preview = await service.preview(project.id, payload)
    payload["expectedPreviewHash"] = preview["previewHash"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post(url, json=payload)
        assert missing.status_code == 400
        assert "提交" in missing.json()["error"]["message"]
        bad = await client.post(url, json={"assetIds": ["bad"], "mode": "custom", "expectedPreviewHash": preview["previewHash"]}, headers={"Idempotency-Key": "bad"})
        assert bad.status_code == 400
        first = await client.post(url, json=payload, headers={"Idempotency-Key": "api"})
        replay = await client.post(url, json=payload, headers={"Idempotency-Key": "api"})
        assert first.status_code == replay.status_code == 202
        assert first.json()["data"]["id"] == replay.json()["data"]["id"]
        saved = (await client.get(url)).json()["data"]
        assert saved[0]["tasks"][0]["outputAssetId"]
    assert len(editor.requests) == 1


@pytest.mark.asyncio
async def test_preview_is_full_prompt_without_persisting_or_generating():
    from backend.app.main import create_app
    from backend.app.core.config import Settings
    service, _, project, _, _, old, editor, _ = await fixture()
    app = create_app(settings=Settings(_env_file=None), project_repository=service.projects, identity_provider=service.identity)
    app.state.style_harmonization_service = service
    payload = {"assetIds": [str(old.id)], "mode": "custom", "prompt": "用户完整风格要求"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post(f"/api/projects/{project.id}/style-harmonizations/preview", json=payload)
        assert result.status_code == 200
        preview = result.json()["data"]
        assert preview["assetIds"] == payload["assetIds"]
        assert preview["mode"] == "custom"
        assert "用户完整风格要求" in preview["finalPrompt"]
        assert await service.list_jobs(project.id) == []
        assert not editor.requests
        job = await service.submit(project.id, payload, "preview-confirm")
        assert job["finalPrompt"] == preview["finalPrompt"]


@pytest.mark.asyncio
async def test_invalid_mode_shape_is_chinese_client_error():
    service, _, project, _, _, old, _, _ = await fixture()
    with pytest.raises(AppError) as error:
        await service.submit(project.id, {"assetIds": [str(old.id)], "mode": []}, "bad-mode")
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_expired_jobs_survive_new_service_without_automatic_retry():
    from backend.app.application.style_harmonization_service import StyleHarmonizationService
    service, _, project, _, _, old, editor, _ = await fixture()
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "风格"}, "expired")
    def expire(state):
        state["job"]["leaseExpiresAt"] = "2000-01-01T00:00:00+00:00"
    await service.repository.change(project.id, service.scope, "style-harmonization:" + job["id"], None, expire)
    restarted = StyleHarmonizationService(service.repository, service.projects, service.storage, service.assets, service.editor, service.archive, service.identity, service.provider_model, service.prompts)
    saved = (await restarted.list_jobs(project.id))[0]
    assert saved["status"] == "failed"
    assert saved["tasks"][0]["error"]
    await restarted.execute(project.id, job["id"])
    assert not editor.requests


@pytest.mark.asyncio
async def test_partial_results_checkpoint_and_remain_candidates_after_interruption():
    import asyncio
    service, _, project, _, white, old, editor, _ = await fixture()
    original_edit = editor.edit
    async def stop_second(request):
        if editor.requests:
            saved = (await service.list_jobs(project.id))[0]
            assert saved["tasks"][0]["outputAssetId"]
            raise asyncio.CancelledError()
        return await original_edit(request)
    editor.edit = stop_second
    job = await service.submit(project.id, {"assetIds": [str(old.id), str(white.id)], "mode": "custom", "prompt": "风格"}, "partial")
    with pytest.raises(asyncio.CancelledError):
        await service.execute(project.id, job["id"])
    saved = (await service.list_jobs(project.id))[0]
    assert saved["status"] == "partial"
    assert [task["status"] for task in saved["tasks"]] == ["succeeded", "failed"]
    assert await service.assets.get_selections(project.id) == {"generated": old.id}


@pytest.mark.asyncio
async def test_candidate_preserves_source_pixel_dimensions_with_supported_provider_ratio():
    from io import BytesIO
    from PIL import Image
    service, _, project, _, _, _, editor, _ = await fixture()
    stream = BytesIO()
    Image.new("RGB", (30, 40), "orange").save(stream, format="PNG")
    source = await service.assets.upload_asset(project.id, "source", stream.getvalue(), "image/png", "portrait.png")
    job = await service.submit(project.id, {"assetIds": [str(source.id)], "mode": "custom", "prompt": "风格"}, "dimensions")
    await service.execute(project.id, job["id"])
    saved = (await service.list_jobs(project.id))[0]
    result = await service.assets.get_preview(project.id, UUID(saved["tasks"][0]["outputAssetId"]))
    with Image.open(BytesIO(result.data)) as output:
        assert output.size == (30, 40)
        assert output.getpixel((15, 0))[:3] == (255, 255, 255)
        assert output.getpixel((15, 20))[:3] == (0, 0, 255)
        assert output.getpixel((15, 39))[:3] == (255, 255, 255)
    assert editor.requests[0].aspect_ratio == "3:4"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["prompt", "source", "reference"])
async def test_preview_hash_rejects_changes_before_provider_or_job_creation(changed):
    service, _, project, source, _, old, editor, _ = await fixture()
    _, version = await service.prompts.create_template_with_version(code="frozen-style", name="风格", kind="generation", kind_name="风格", execution_target="image", body="预览正文", user_prompt_template="")
    payload = {"assetIds": [str(old.id)], "mode": "prompt", "promptVersionId": str(version.id)}
    if changed == "reference":
        payload = {"assetIds": [str(old.id)], "mode": "reference", "referenceAssetId": str(source.id)}
    preview = await service.preview(project.id, payload)
    assert len(preview["previewHash"]) == 64
    if changed == "prompt":
        version.body = "另一个提示词正文"
    else:
        asset = source if changed == "reference" else old
        obj = await service.projects.get_object(asset.object_id, service.scope)
        obj.sha256 = "changed"
    with pytest.raises(AppError) as error:
        await service.submit(project.id, payload | {"expectedPreviewHash": preview["previewHash"]}, "confirm")
    assert error.value.status_code == 409
    assert await service.list_jobs(project.id) == []
    assert not editor.requests


@pytest.mark.asyncio
async def test_confirmed_preview_hash_accepts_matching_request_and_replays():
    service, _, project, _, _, old, _, _ = await fixture()
    payload = {"assetIds": [str(old.id)], "mode": "custom", "prompt": "精确预览"}
    preview = await service.preview(project.id, payload)
    confirmed = payload | {"expectedPreviewHash": preview["previewHash"]}
    job = await service.submit(project.id, confirmed, "confirmed")
    assert job["previewHash"] == preview["previewHash"]
    assert await service.submit(project.id, confirmed, "confirmed") == job


@pytest.mark.asyncio
async def test_archive_failure_retains_paid_candidate_with_visible_error_and_no_regeneration():
    service, _, project, _, _, old, editor, archive = await fixture()
    async def fail_archive(**kwargs):
        raise RuntimeError("private archive error")
    archive.archive_project_output = fail_archive
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "风格"}, "archive-fail")
    await service.execute(project.id, job["id"])
    saved = (await service.list_jobs(project.id))[0]
    task = saved["tasks"][0]
    assert task["status"] == "succeeded"
    assert task["outputAssetId"]
    assert "归档" in task["error"]
    assert task["archiveError"] == task["error"]
    assert task["archiveStatus"] == "failed"
    candidate = await service.projects.get_asset(UUID(task["outputAssetId"]), service.scope)
    assert candidate.state == "available"
    assert "private" not in str(saved)
    await service.execute(project.id, job["id"])
    assert len(editor.requests) == 1


@pytest.mark.asyncio
async def test_archive_interruption_keeps_candidate_and_exposes_incomplete_archive():
    import asyncio
    service, _, project, _, _, old, _, archive = await fixture()
    async def interrupted_archive(**kwargs):
        raise asyncio.CancelledError()
    archive.archive_project_output = interrupted_archive
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "风格"}, "archive-interrupt")
    with pytest.raises(asyncio.CancelledError):
        await service.execute(project.id, job["id"])
    task = (await service.list_jobs(project.id))[0]["tasks"][0]
    assert task["status"] == "succeeded" and task["outputAssetId"]
    assert task["archiveStatus"] == "failed" and task["archiveError"]


@pytest.mark.asyncio
async def test_excessive_source_dimensions_rejected_before_provider():
    service, _, project, _, _, old, editor, _ = await fixture()
    obj = await service.projects.get_object(old.object_id, service.scope)
    obj.width, obj.height = 10000, 10000
    with pytest.raises(AppError) as error:
        await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "风格"}, "oversize")
    assert error.value.status_code == 400
    assert not editor.requests


@pytest.mark.asyncio
async def test_provider_image_pixel_limit_is_checked_before_decode_and_candidate_creation():
    import struct
    import zlib
    from backend.app.application.hero_generation_ports import ImageEditResult
    service, _, project, _, _, old, editor, _ = await fixture()
    body = bytearray(png("blue"))
    body[16:24] = struct.pack(">II", 8000, 8000)
    body[29:33] = struct.pack(">I", zlib.crc32(body[12:29]) & 0xFFFFFFFF)
    original_edit = editor.edit
    async def huge_output(request):
        await original_edit(request)
        return ImageEditResult(bytes(body), "image/png", {})
    editor.edit = huge_output
    before = await service.projects.list_assets(project.id, service.scope)
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "风格"}, "large-output")
    await service.execute(project.id, job["id"])
    saved = (await service.list_jobs(project.id))[0]
    assert saved["status"] == "failed"
    assert saved["tasks"][0]["outputAssetId"] is None
    assert len(await service.projects.list_assets(project.id, service.scope)) == len(before)


@pytest.mark.asyncio
async def test_image_decoding_and_candidate_rendering_run_off_event_loop(monkeypatch):
    import threading
    from backend.app.application import style_harmonization_service as module
    service, _, project, _, _, old, _, _ = await fixture()
    main_thread = threading.get_ident()
    calls = []
    real_check = module._check_image
    def checked(*args, **kwargs):
        calls.append(threading.get_ident())
        return real_check(*args, **kwargs)
    monkeypatch.setattr(module, "_check_image", checked)
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "风格"}, "threaded")
    await service.execute(project.id, job["id"])
    assert (await service.list_jobs(project.id))[0]["status"] == "succeeded"
    assert len(calls) >= 2 and all(thread != main_thread for thread in calls)


@pytest.mark.asyncio
async def test_project_asset_link_failure_keeps_already_written_candidate():
    service, _, project, _, _, old, editor, _ = await fixture()
    class BrokenLink:
        async def link_project_asset(self, project, asset):
            raise RuntimeError("private link failure")
    service.assets.project_archive = BrokenLink()
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "风格"}, "link-failure")
    await service.execute(project.id, job["id"])
    task = (await service.list_jobs(project.id))[0]["tasks"][0]
    assert task["status"] == "succeeded"
    assert task["outputAssetId"] and task["archiveError"]
    output = await service.projects.get_asset(UUID(task["outputAssetId"]), service.scope)
    assert output.state == "available"
    await service.execute(project.id, job["id"])
    assert len(editor.requests) == 1


@pytest.mark.asyncio
async def test_exif_source_and_candidate_keep_display_orientation():
    from io import BytesIO
    from PIL import Image
    from backend.app.application.hero_generation_ports import ImageEditResult
    service, _, project, _, _, _, editor, _ = await fixture()
    buffer = BytesIO()
    picture = Image.new("RGB", (40, 30), "blue")
    exif = picture.getexif(); exif[274] = 6
    picture.save(buffer, "JPEG", exif=exif)
    source = await service.assets.upload_asset(project.id, "source", buffer.getvalue(), "image/jpeg", "rotated.jpg")
    original_edit = editor.edit
    async def rotated_output(request):
        await original_edit(request)
        return ImageEditResult(buffer.getvalue(), "image/jpeg", {})
    editor.edit = rotated_output
    job = await service.submit(project.id, {"assetIds": [str(source.id)], "mode": "custom", "prompt": "风格"}, "exif")
    await service.execute(project.id, job["id"])
    assert editor.requests[0].aspect_ratio == "3:4"
    task = (await service.list_jobs(project.id))[0]["tasks"][0]
    result = await service.assets.get_preview(project.id, UUID(task["outputAssetId"]))
    with Image.open(BytesIO(result.data)) as candidate:
        assert candidate.size == (30, 40)
        assert candidate.getpixel((15, 0))[2] > 200
        assert candidate.getpixel((15, 0))[0] < 10


@pytest.mark.asyncio
@pytest.mark.parametrize("hash_value", [None, "", "bad"])
async def test_api_requires_preview_confirmation_before_generation(hash_value):
    from backend.app.main import create_app
    from backend.app.core.config import Settings
    service, _, project, _, _, old, editor, _ = await fixture()
    app = create_app(settings=Settings(_env_file=None), project_repository=service.projects, identity_provider=service.identity)
    app.state.style_harmonization_service = service
    payload = {"assetIds": [str(old.id)], "mode": "custom", "prompt": "风格"}
    if hash_value is not None:
        payload["expectedPreviewHash"] = hash_value
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/projects/{project.id}/style-harmonizations", json=payload, headers={"Idempotency-Key": "unconfirmed"})
    assert response.status_code == 409
    assert not editor.requests
    assert await service.list_jobs(project.id) == []
