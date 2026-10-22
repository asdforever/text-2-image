import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
import pytest

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.project_repository import InMemoryProjectRepository
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


WORKSPACE = UUID(int=11)


async def add_asset(repository, project, kind="source", **kwargs):
    obj = await repository.create_object(
        project.workspace_id, "private/original.png", "product.png", "image/png",
        1024, 32, 24, "a" * 64,
    )
    asset = await repository.create_asset(project.id, obj.id, kind, **kwargs)
    return asset, obj


def client_for(repository):
    app = create_app(
        settings=Settings(_env_file=None, local_workspace_id=WORKSPACE),
        repository=InMemoryRepository(), storage=MemoryObjectStorage(),
        project_repository=repository,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_project_list_includes_lightweight_counts_and_generated_first_cover():
    async def run():
        repo = InMemoryProjectRepository()
        project = await repo.create_project("商品", WORKSPACE)
        empty = await repo.create_project("空项目", WORKSPACE)
        archived = await repo.create_project("归档", WORKSPACE)
        foreign = await repo.create_project("其他空间", UUID(int=22))
        old_source, _ = await add_asset(repo, project)
        source, _ = await add_asset(repo, project)
        generated, _ = await add_asset(repo, project, "generated")
        deleted, _ = await add_asset(repo, project)
        deleted.state = "deleted"
        pending, _ = await add_asset(repo, project)
        pending.state = "cleanup_pending"
        now = datetime.now(timezone.utc)
        old_source.created_at = now - timedelta(days=2)
        source.created_at = now - timedelta(days=1)
        generated.created_at = now
        await repo.archive_project(archived.id, WORKSPACE)
        await add_asset(repo, foreign)
        async with client_for(repo) as client:
            response = await client.get("/api/projects")
            rows = {r["id"]: r for r in response.json()["data"]}
            assert set(rows) == {str(project.id), str(empty.id)}
            assert rows[str(project.id)]["assetCount"] == 4
            assert rows[str(project.id)]["coverAssetId"] == str(generated.id)
            assert rows[str(empty.id)]["assetCount"] == 0
            assert rows[str(empty.id)]["coverAssetId"] is None
            assert "assets" not in rows[str(project.id)]
            assert "private/" not in response.text
            all_rows = (await client.get("/api/projects?includeArchived=true")).json()["data"]
            assert {r["id"] for r in all_rows} == {str(project.id), str(empty.id), str(archived.id)}
            generated.state = "deleted"
            fallback = (await client.get("/api/projects")).json()["data"]
            assert next(r for r in fallback if r["id"] == str(project.id))["coverAssetId"] is None
    asyncio.run(run())


def test_cover_prefers_latest_usable_generated_image_then_white_background():
    async def run():
        repo = InMemoryProjectRepository()
        project = await repo.create_project("生成结果封面", WORKSPACE)
        now = datetime.now(timezone.utc)
        source, _ = await add_asset(repo, project)
        old_result, _ = await add_asset(repo, project, "generated")
        result, obj = await add_asset(repo, project, "generated")
        white, _ = await add_asset(repo, project, "white_background")
        source.created_at = white.created_at = now
        old_result.created_at = now - timedelta(days=2)
        result.created_at = now - timedelta(days=1)
        async with client_for(repo) as client:
            async def cover():
                rows = (await client.get("/api/projects")).json()["data"]
                return rows[0]["coverAssetId"]

            assert await cover() == str(result.id)
            obj.state = "cleanup_pending"
            assert await cover() == str(old_result.id)
            old_result.state = "deleted"
            assert await cover() == str(white.id)
            white.state = "cleanup_pending"
            assert await cover() is None

    asyncio.run(run())


@pytest.mark.parametrize("asset_count", [1, 25])
def test_project_details_and_asset_lists_do_not_read_each_asset_separately(asset_count):
    class CountingRepository(InMemoryProjectRepository):
        individual_asset_reads = 0

        async def get_asset(self, *args):
            self.individual_asset_reads += 1
            return await super().get_asset(*args)

    async def run():
        repo = CountingRepository()
        project = await repo.create_project("商品", WORKSPACE)
        assets = [await add_asset(repo, project, source_snapshot={"origin": "retained"}) for _ in range(asset_count)]
        await repo.select_asset(project.id, "source", assets[0][0].id, WORKSPACE)
        repo.individual_asset_reads = 0
        async with client_for(repo) as client:
            response = await client.get(f"/api/projects/{project.id}")
            listed = await client.get(f"/api/projects/{project.id}/assets")
            data = response.json()["data"]
            assert response.status_code == listed.status_code == 200
            assert len(data["assets"]) == asset_count
            assert data["assets"] == listed.json()["data"]
            assert data["assets"][0]["sourceSnapshot"] == {"origin": "retained"}
            assert data["selections"] == {"source": str(assets[0][0].id)}
            assert repo.individual_asset_reads == 0
    asyncio.run(run())


def test_bulk_asset_reads_preserve_missing_object_errors_and_workspace_isolation():
    async def run():
        repo = InMemoryProjectRepository()
        project = await repo.create_project("商品", WORKSPACE)
        asset, obj = await add_asset(repo, project)
        foreign = await repo.create_project("私有项目", UUID(int=22))
        await add_asset(repo, foreign)
        async with client_for(repo) as client:
            assert (await client.get(f"/api/projects/{foreign.id}")).status_code == 404
            assert (await client.get(f"/api/projects/{foreign.id}/assets")).json()["data"] == []
            for state in ["cleanup_pending", "cleaned"]:
                obj.state = state
                for path in [f"/api/projects/{project.id}", f"/api/projects/{project.id}/assets"]:
                    result = await client.get(path)
                    assert result.status_code == 404
                    assert result.json()["error"]["code"] == "OBJECT_NOT_FOUND"
            obj.state = "available"
            obj.workspace_id = UUID(int=22)
            assert (await client.get(f"/api/projects/{project.id}/assets")).status_code == 404
            repo._objects.pop(obj.id)
            assert (await client.get(f"/api/projects/{project.id}/assets")).status_code == 404
            asset.state = "deleted"
            assert (await client.get(f"/api/projects/{project.id}/assets")).json()["data"] == []
    asyncio.run(run())
