import asyncio
from datetime import datetime, timezone
from uuid import UUID

import httpx

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.repository import InMemoryRepository
from backend.app.storage import MemoryObjectStorage


NOW = datetime(2026, 9, 14, 9, 0, tzinfo=timezone.utc).isoformat()


class _AssetService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def list_libraries(self):
        self.calls.append(("list_libraries",))
        return [{"id": str(UUID(int=101)), "name": "素材库", "description": "", "assetType": "image", "createdAt": NOW, "updatedAt": NOW}]

    async def create_library(self, payload):
        self.calls.append(("create_library", payload))
        return {"id": str(UUID(int=102)), "name": payload["name"], "description": "", "assetType": payload["assetType"], "createdAt": NOW, "updatedAt": NOW}

    async def get_library(self, library_id):
        self.calls.append(("get_library", library_id))
        return {"id": library_id, "name": "素材库"}

    async def update_library(self, library_id, payload):
        self.calls.append(("update_library", library_id, payload))
        return {"id": library_id, **payload}

    async def delete_library(self, library_id):
        self.calls.append(("delete_library", library_id))

    async def list_assets(self, library_id):
        self.calls.append(("list_assets", library_id))
        return []

    async def create_asset(self, library_id, payload):
        self.calls.append(("create_asset", library_id, payload))
        return {"id": str(UUID(int=103)), "libraryId": library_id, "name": payload["name"]}

    async def delete_asset(self, library_id, asset_id):
        self.calls.append(("delete_asset", library_id, asset_id))


class _ProductService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def list_libraries(self):
        self.calls.append(("list_libraries",))
        return [{"id": str(UUID(int=201)), "name": "产物库", "description": "", "libraryType": "manual", "createdAt": NOW, "updatedAt": NOW}]

    async def create_library(self, payload):
        self.calls.append(("create_library", payload))
        return {"id": str(UUID(int=202)), **payload}

    async def get_library(self, library_id):
        self.calls.append(("get_library", library_id))
        return {"id": library_id, "name": "产物库"}

    async def update_library(self, library_id, payload):
        self.calls.append(("update_library", library_id, payload))
        return {"id": library_id, **payload}

    async def delete_library(self, library_id):
        self.calls.append(("delete_library", library_id))

    async def list_products(self, library_id):
        self.calls.append(("list_products", library_id))
        return []

    async def create_product(self, library_id, payload):
        self.calls.append(("create_product", library_id, payload))
        return {"id": str(UUID(int=203)), "libraryId": library_id, "name": payload["name"]}

    async def delete_product(self, library_id, product_id):
        self.calls.append(("delete_product", library_id, product_id))


class _TestRunService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def list_runs(self, prompt_version_id=None):
        self.calls.append(("list_runs", prompt_version_id))
        return [{"id": str(UUID(int=301)), "promptVersionId": str(UUID(int=302)), "status": "pending", "createdAt": NOW}]

    async def create_run(self, payload):
        self.calls.append(("create_run", payload))
        return {"id": str(UUID(int=303)), "promptVersionId": payload["promptVersionId"], "inputAssetId": None, "inputText": payload["inputText"], "status": "pending", "createdAt": NOW}

    async def get_run(self, run_id):
        self.calls.append(("get_run", run_id))
        return {"id": run_id, "status": "pending"}

    async def update_run(self, run_id, payload):
        self.calls.append(("update_run", run_id, payload))
        return {"id": run_id, **payload}

    async def delete_run(self, run_id):
        self.calls.append(("delete_run", run_id))


def test_database_dependent_routes_can_run_with_replaced_services() -> None:
    async def run() -> None:
        assets = _AssetService()
        products = _ProductService()
        test_runs = _TestRunService()
        app = create_app(
            settings=Settings(_env_file=None),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
            asset_service=assets,
            product_service=products,
            test_run_service=test_runs,
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            asset_list = await client.get("/api/asset-libraries")
            asset_created = await client.post(
                "/api/asset-libraries", json={"name": "新素材库", "assetType": "text"}
            )
            product_list = await client.get("/api/test-product-libraries")
            run_list = await client.get(
                "/api/test-runs", params={"prompt_version_id": str(UUID(int=302))}
            )
            run_created = await client.post(
                "/api/test-runs",
                json={"promptVersionId": str(UUID(int=302)), "inputText": "测试输入"},
            )

        assert asset_list.status_code == 200
        assert asset_list.json()["data"][0]["name"] == "素材库"
        assert asset_created.status_code == 201
        assert product_list.status_code == 200
        assert run_list.status_code == 200
        assert run_created.status_code == 201
        assert assets.calls == [
            ("list_libraries",),
            ("create_library", {"name": "新素材库", "assetType": "text"}),
        ]
        assert products.calls == [("list_libraries",)]
        assert test_runs.calls[0] == ("list_runs", str(UUID(int=302)))

    asyncio.run(run())


def test_all_library_mutations_delegate_without_database_or_storage_clients() -> None:
    async def run() -> None:
        assets = _AssetService()
        products = _ProductService()
        test_runs = _TestRunService()
        app = create_app(
            settings=Settings(_env_file=None),
            repository=InMemoryRepository(),
            storage=MemoryObjectStorage(),
            asset_service=assets,
            product_service=products,
            test_run_service=test_runs,
        )
        asset_library_id = str(UUID(int=101))
        asset_id = str(UUID(int=103))
        product_library_id = str(UUID(int=201))
        product_id = str(UUID(int=203))
        run_id = str(UUID(int=301))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            responses = [
                await client.get(f"/api/asset-libraries/{asset_library_id}"),
                await client.patch(f"/api/asset-libraries/{asset_library_id}", json={"name": "改名"}),
                await client.get(f"/api/asset-libraries/{asset_library_id}/assets"),
                await client.post(
                    f"/api/asset-libraries/{asset_library_id}/assets",
                    data={"name": "图片"},
                    files={"file": ("item.png", b"image-data", "image/png")},
                ),
                await client.delete(f"/api/asset-libraries/{asset_library_id}/assets/{asset_id}"),
                await client.delete(f"/api/asset-libraries/{asset_library_id}"),
                await client.post("/api/test-product-libraries", json={"name": "新产物库", "libraryType": "manual"}),
                await client.get(f"/api/test-product-libraries/{product_library_id}"),
                await client.patch(f"/api/test-product-libraries/{product_library_id}", json={"name": "改名"}),
                await client.get(f"/api/test-product-libraries/{product_library_id}/products"),
                await client.post(
                    f"/api/test-product-libraries/{product_library_id}/products",
                    data={"name": "产物", "productType": "image"},
                    files={"file": ("result.png", b"result-data", "image/png")},
                ),
                await client.delete(f"/api/test-product-libraries/{product_library_id}/products/{product_id}"),
                await client.delete(f"/api/test-product-libraries/{product_library_id}"),
                await client.get(f"/api/test-runs/{run_id}"),
                await client.patch(f"/api/test-runs/{run_id}", json={"status": "running"}),
                await client.delete(f"/api/test-runs/{run_id}"),
            ]

        assert [response.status_code for response in responses] == [
            200, 200, 200, 201, 204, 204, 201, 200, 200, 200, 201, 204, 204, 200, 200, 204
        ]
        asset_upload = next(call for call in assets.calls if call[0] == "create_asset")
        product_upload = next(call for call in products.calls if call[0] == "create_product")
        assert asset_upload[2]["fileData"] == b"image-data"
        assert product_upload[2]["fileData"] == b"result-data"

    asyncio.run(run())
