from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from backend.app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


def make_app():
    identity = LocalSingleUserIdentityProvider(
        IdentityContext(uuid4(), uuid4(), "owner")
    )
    return create_app(
        settings=Settings(_env_file=None),
        repository=InMemoryRepository(),
        storage=MemoryObjectStorage(),
        identity_provider=identity,
    )


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16), "white").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_created_production_library_can_be_opened_by_id() -> None:
    app = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/product-libraries",
            json={"name": "正式成品", "description": "已确认发布的交付版本"},
        )
        library_id = created.json()["data"]["id"]

        opened = await client.get(f"/api/product-libraries/{library_id}")

    assert opened.status_code == 200
    assert opened.json()["data"] == created.json()["data"]


@pytest.mark.asyncio
async def test_project_upload_appears_in_automatic_product_archive() -> None:
    app = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        project = await client.post(
            "/api/projects",
            headers={"Idempotency-Key": "project-for-upload"},
            json={"name": "上传隔离验证"},
        )
        project_id = project.json()["data"]["id"]

        uploaded = await client.post(
            f"/api/projects/{project_id}/assets",
            headers={"Idempotency-Key": "direct-upload"},
            data={"kind": "source"},
            files={"file": ("source.png", png_bytes(), "image/png")},
        )
        libraries = await client.get("/api/product-libraries")
        archive_library = next(
            item for item in libraries.json()["data"] if item["name"] == "项目成品库"
        )
        products = await client.get(
            f"/api/product-libraries/{archive_library['id']}/products"
        )

    assert uploaded.status_code == 201
    assert products.status_code == 200
    archived = products.json()["data"]
    assert len(archived) == 1
    assert archived[0]["projectId"] == project_id
    assert archived[0]["assets"] == [
        {
            "id": uploaded.json()["data"]["id"],
            "kind": "source",
            "sourceKind": "upload",
            "originalFilename": "source.png",
            "mimeType": "image/png",
            "fileSize": len(png_bytes()),
            "width": 16,
            "height": 16,
            "previewUrl": f"/api/projects/{project_id}/assets/{uploaded.json()['data']['id']}/preview",
            "sourceSnapshot": {},
            "versions": [],
        }
    ]


@pytest.mark.asyncio
async def test_published_product_version_exposes_controlled_preview_route() -> None:
    app = make_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        library = await client.post("/api/product-libraries", json={"name": "正式成品"})
        library_id = library.json()["data"]["id"]
        product = await client.post(
            f"/api/product-libraries/{library_id}/products", json={"name": "鼠标"}
        )
        product_id = product.json()["data"]["id"]
        published = await client.post(
            f"/api/product-libraries/{library_id}/products/{product_id}/versions/publish",
            headers={"Idempotency-Key": "preview-publish"},
            json={
                "productType": "hero",
                "sourceVersion": {
                    "id": "source-version",
                    "status": "succeeded",
                    "previewUrl": "/api/projects/project/versions/source-version/preview",
                },
            },
        )
        version_id = published.json()["data"]["id"]
        preview = await client.get(
            f"/api/products/{product_id}/versions/{version_id}/preview"
        )

    assert published.status_code == 201
    assert preview.status_code == 307
    assert preview.headers["location"] == "/api/projects/project/versions/source-version/preview"
