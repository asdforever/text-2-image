import asyncio
from io import BytesIO
from uuid import UUID

import httpx
from PIL import Image

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


def _png(color: str = "red") -> bytes:
    image = Image.new("RGB", (16, 9), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_project_api_uses_server_workspace_and_uniform_response_contract() -> None:
    async def run() -> None:
        project_repository = InMemoryProjectRepository()
        app = create_app(
            settings=Settings(_env_file=None, local_workspace_id=UUID(int=11)),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
            project_repository=project_repository,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/projects",
                json={"name": "  键盘项目  ", "workspaceId": str(UUID(int=22))},
                headers={"Idempotency-Key": "project-api-key"},
            )
            project_id = created.json()["data"]["id"]
            listed = await client.get("/api/projects")
            fetched = await client.get(f"/api/projects/{project_id}")
            archived = await client.post(f"/api/projects/{project_id}/archive")
            default_list = await client.get("/api/projects")
            all_projects = await client.get("/api/projects?includeArchived=true")

        assert created.status_code == 201
        assert created.json()["data"]["name"] == "键盘项目"
        assert "workspaceId" not in created.json()["data"]
        assert project_repository._projects[UUID(project_id)].workspace_id == UUID(int=11)
        assert [item["id"] for item in listed.json()["data"]] == [project_id]
        assert fetched.json()["data"]["id"] == project_id
        assert archived.json()["data"]["status"] == "archived"
        assert default_list.json()["data"] == []
        assert [item["id"] for item in all_projects.json()["data"]] == [project_id]

    asyncio.run(run())


def test_project_asset_api_uploads_versions_selects_and_previews() -> None:
    async def run() -> None:
        app = create_app(
            settings=Settings(_env_file=None),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
            project_repository=InMemoryProjectRepository(),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            project = await client.post("/api/projects", json={"name": "键盘项目"})
            project_id = project.json()["data"]["id"]
            source = await client.post(
                f"/api/projects/{project_id}/assets",
                data={"kind": "source"},
                files={"file": ("keyboard.png", _png(), "image/png")},
            )
            source_id = source.json()["data"]["id"]
            white = await client.post(
                f"/api/projects/{project_id}/assets",
                data={"kind": "white_background", "sourceAssetId": source_id},
                files={"file": ("white.png", _png("white"), "image/png")},
            )
            white_id = white.json()["data"]["id"]
            selected = await client.put(
                f"/api/projects/{project_id}/selections/white_background",
                json={"assetId": white_id},
            )
            detail = await client.get(f"/api/projects/{project_id}")
            preview = await client.get(
                f"/api/projects/{project_id}/assets/{white_id}/preview"
            )

        assert source.status_code == 201
        assert white.json()["data"]["sourceAssetId"] == source_id
        assert selected.json()["data"]["id"] == white_id
        assert {asset["id"] for asset in detail.json()["data"]["assets"]} == {source_id, white_id}
        assert detail.json()["data"]["selections"] == {"white_background": white_id}
        assert preview.status_code == 200
        assert preview.content == _png("white")

    asyncio.run(run())


def test_project_asset_preview_hides_storage_key_for_out_of_scope_asset() -> None:
    async def run() -> None:
        project_repository = InMemoryProjectRepository()
        other_workspace = UUID(int=22)
        other_project = await project_repository.create_project("其他项目", other_workspace)
        object_record = await project_repository.create_object(
            other_workspace,
            "projects/private-object-key/original.png",
            "private.png",
            "image/png",
            128,
            16,
            9,
            "a" * 64,
        )
        asset = await project_repository.create_asset(other_project.id, object_record.id, "source")
        app = create_app(
            settings=Settings(_env_file=None, local_workspace_id=UUID(int=11)),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
            project_repository=project_repository,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/projects/{other_project.id}/assets/{asset.id}/preview",
                headers={"X-Request-ID": "project-security-1"},
            )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "INVALID_PROJECT_ASSET_ID"
        assert response.json()["requestId"] == "project-security-1"
        assert "private-object-key" not in response.text

    asyncio.run(run())
