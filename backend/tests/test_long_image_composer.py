from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import httpx
import pytest
from PIL import Image

from backend.app.core.config import Settings
from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.main import create_app
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.project_storage import MemoryProjectAssetStorage


def png(color, size=(320, 160)):
    result = BytesIO()
    Image.new("RGBA", size, color).save(result, "PNG")
    return result.getvalue()


async def setup():
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), uuid4(), "owner"))
    projects = InMemoryProjectRepository()
    storage = MemoryProjectAssetStorage()
    app = create_app(settings=Settings(_env_file=None), project_repository=projects, project_asset_storage=storage, identity_provider=identity)
    project = await app.state.project_service.create_project("长图测试")
    assets = app.state.project_asset_service
    red = await assets.upload_asset(project.id, "source", png("red"), "image/png", "红图.png")
    blue = await assets.upload_asset(project.id, "source", png("blue", (320, 320)), "image/png", "蓝图.png")
    body = {"title": "详情长图", "width": 320, "gap": 10, "background": "#ffffff", "items": [{"assetId": str(red.id)}, {"assetId": str(blue.id), "paddingTop": 5, "paddingBottom": 15}]}
    return app, project, red, blue, body


@pytest.mark.asyncio
async def test_save_long_image_archives_recipe_and_downloads_pixel_exact_slices():
    app, project, red, blue, body = await setup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/projects/{project.id}/long-images"
        result = await client.post(url, json=body, headers={"Idempotency-Key": "save-once"})
        assert result.status_code == 201, result.text
        saved = result.json()["data"]
        assert (saved["width"], saved["height"]) == (320, 510)
        assert saved["recipe"]["items"][0]["assetId"] == str(red.id)
        replay = await client.post(url, json=body, headers={"Idempotency-Key": "save-once"})
        assert replay.json()["data"]["assetId"] == saved["assetId"]
        conflict = await client.post(url, json={**body, "gap": 20}, headers={"Idempotency-Key": "save-once"})
        assert conflict.status_code == 409
        records = (await client.get(url)).json()["data"]
        assert len(records) == 1
        downloaded = await client.get(f"{url}/{saved['assetId']}/download")
        assert downloaded.status_code == 200
        image = Image.open(BytesIO(downloaded.content))
        assert image.getpixel((10, 159)) == (255, 0, 0)
        assert image.getpixel((10, 160)) == (255, 255, 255)
        assert image.getpixel((10, 174)) == (255, 255, 255)
        assert image.getpixel((10, 175)) == (0, 0, 255)
        zipped = await client.get(f"{url}/{saved['assetId']}/download?sliceHeight=256")
        with ZipFile(BytesIO(zipped.content)) as archive:
            assert archive.namelist() == ["001.png", "002.png"]
            parts = [Image.open(BytesIO(archive.read(name))) for name in archive.namelist()]
            assert [part.height for part in parts] == [256, 254]
            rebuilt = Image.new("RGB", (320, 510))
            rebuilt.paste(parts[0], (0, 0)); rebuilt.paste(parts[1], (0, 256))
            assert rebuilt.tobytes() == image.tobytes()
        assert (await app.state.project_asset_service.get_preview(project.id, red.id)).data == png("red")
        product = await app.state.product_library_service.get_project_product(project.id)
        versions = await app.state.product_library_service.list_versions(product.id)
        assert len(versions) == 1
        assert versions[0].product_type == "detail"
        assert versions[0].source_snapshot["recipe"] == saved["recipe"]
        assets = await app.state.project_asset_service.list_assets(project.id)
        output = next(a for a in assets if str(a.id) == saved["assetId"])
        assert output.source_kind == "long_image"
        assert len(output.source_snapshot["sources"]) == 2
        assert output.source_snapshot["sources"][0]["sha256"]


@pytest.mark.asyncio
async def test_long_image_rejects_foreign_deleted_and_oversized_sources_without_writes():
    app, project, red, blue, body = await setup()
    other = await app.state.project_service.create_project("其他项目")
    foreign = await app.state.project_asset_service.upload_asset(other.id, "source", png("green"), "image/png", "外部.png")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/projects/{project.id}/long-images"
        for invalid in [
            {**body, "items": [{"assetId": str(foreign.id)}]},
            {**body, "items": []},
            {**body, "width": 0},
            {**body, "items": [{"assetId": str(red.id), "crop": {"top": 90}}]},
            {**body, "width": 1600, "items": [{"assetId": str(blue.id)}] * 20},
        ]:
            response = await client.post(url, json=invalid, headers={"Idempotency-Key": str(uuid4())})
            assert response.status_code in {400, 404, 409, 422}, response.text
        await app.state.project_asset_service.delete_asset(project.id, red.id)
        assert (await client.post(url, json=body, headers={"Idempotency-Key": "deleted"})).status_code == 409
        assert (await client.get(url)).json()["data"] == []
        assert (await client.get(f"/api/projects/{uuid4()}/long-images")).status_code == 404


@pytest.mark.asyncio
async def test_archive_failure_can_retry_without_duplicate_long_image():
    app, project, red, blue, body = await setup()
    archive = app.state.product_library_service
    original = archive.archive_project_output
    async def fail(**kwargs):
        raise RuntimeError("archive unavailable")
    archive.archive_project_output = fail
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        url = f"/api/projects/{project.id}/long-images"
        first = await client.post(url, json=body, headers={"Idempotency-Key": "retry-archive"})
        assert first.status_code == 503
        archive.archive_project_output = original
        retry = await client.post(url, json=body, headers={"Idempotency-Key": "retry-archive"})
        assert retry.status_code == 201
        assert len((await client.get(url)).json()["data"]) == 1


@pytest.mark.asyncio
async def test_transient_asset_write_failure_allows_same_key_retry():
    app, project, red, blue, body = await setup()
    storage = app.state.project_asset_service.storage
    original = storage.put
    async def fail_once(obj):
        storage.put = original
        raise RuntimeError("storage unavailable")
    storage.put = fail_once
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/projects/{project.id}/long-images"
        first = await client.post(url, json=body, headers={"Idempotency-Key": "retry-write"})
        assert first.status_code == 503
        retry = await client.post(url, json=body, headers={"Idempotency-Key": "retry-write"})
        assert retry.status_code == 201, retry.text
        assert len((await client.get(url)).json()["data"]) == 1


def test_render_crops_edges_composites_transparency_and_preserves_aspect_ratio():
    from backend.app.application.long_image_rendering import LongImageRecipe, render_long_image
    asset_id = str(uuid4())
    source = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    source.paste((255, 0, 0, 255), (0, 0, 100, 200))
    data = BytesIO(); source.save(data, "PNG")
    recipe = LongImageRecipe.model_validate({"title": "裁剪", "width": 320, "background": "#00ff00", "items": [{"assetId": asset_id, "crop": {"left": 25}, "paddingTop": 10}]})
    body, width, height = render_long_image(recipe, [data.getvalue()])
    assert (width, height) == (320, 223)
    result = Image.open(BytesIO(body))
    assert result.getpixel((160, 100)) == (0, 255, 0)
    assert source.size == (400, 200)


def test_exif_orientation_is_applied_before_layout():
    from backend.app.application.long_image_rendering import LongImageRecipe, render_long_image
    source = Image.new("RGB", (320, 160), "red")
    exif = Image.Exif(); exif[274] = 6
    data = BytesIO(); source.save(data, "JPEG", exif=exif)
    recipe = LongImageRecipe.model_validate({"title": "方向", "width": 320, "items": [{"assetId": str(uuid4())}]})
    result, width, height = render_long_image(recipe, [data.getvalue()])
    assert (width, height) == (320, 640)
    assert Image.open(BytesIO(result)).size == (320, 640)


@pytest.mark.asyncio
async def test_saved_image_survives_source_deletion_but_new_composition_requires_live_source():
    app, project, red, blue, body = await setup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/projects/{project.id}/long-images"
        saved = (await client.post(url, json=body, headers={"Idempotency-Key": "original"})).json()["data"]
        await app.state.project_asset_service.delete_asset(project.id, blue.id)
        assert (await client.get(f"{url}/{saved['assetId']}/download")).status_code == 200
        assert (await client.post(url, json=saved["recipe"], headers={"Idempotency-Key": "new"})).status_code == 409
        assert (await client.post(url, json=body, headers={"Idempotency-Key": "original"})).json()["data"]["assetId"] == saved["assetId"]


@pytest.mark.asyncio
async def test_changed_source_bytes_are_rejected_and_concurrent_retries_save_one_asset():
    import asyncio
    from backend.app.storage import StoredObject
    app, project, red, blue, body = await setup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/projects/{project.id}/long-images"
        responses = await asyncio.gather(*(client.post(url, json=body, headers={"Idempotency-Key": "concurrent"}) for _ in range(2)))
        assert responses[0].json()["data"]["assetId"] == responses[1].json()["data"]["assetId"]
        _, obj = await app.state.project_asset_service.get_asset_details(project.id, red.id)
        await app.state.project_asset_service.storage.put(StoredObject(obj.storage_key, png("green"), "image/png"))
        response = await client.post(url, json=body, headers={"Idempotency-Key": "changed"})
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "LONG_IMAGE_SOURCE_CHANGED"
