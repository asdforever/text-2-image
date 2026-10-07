from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from PIL import Image

from app.core.config import Settings
from app.main import create_app
from app.project_repository import InMemoryProjectRepository
from app.project_storage import MemoryProjectAssetStorage
from app.repository import InMemoryRepository
from app.reverse_project_repository import InMemoryReverseProjectRepository


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 6), "red").save(output, format="PNG")
    return output.getvalue()


class FakeReverseExecutionGenerationService:
    def __init__(self):
        self.calls = []

    async def generate(self, project_id, expected_revision, **kwargs):
        self.calls.append((project_id, expected_revision, kwargs))
        return SimpleNamespace(
            id=UUID("11111111-1111-1111-1111-111111111111"),
            project_id=project_id,
            reverse_version_id=UUID("22222222-2222-2222-2222-222222222222"),
            document={"versionId": "22222222-2222-2222-2222-222222222222", "tasks": []},
            revision=expected_revision + 1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_project_reverse_execution_api_generates_and_compiles_tasks():
    app = create_app(
        settings=Settings(_env_file=None, local_workspace_id=UUID(int=11)),
        repository=InMemoryRepository(),
        project_repository=InMemoryProjectRepository(),
        project_asset_storage=MemoryProjectAssetStorage(),
        reverse_project_repository=InMemoryReverseProjectRepository(),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        business = (await client.post("/api/projects", json={"name": "鼠标项目"})).json()["data"]
        reverse = (await client.post("/api/reverse-projects", json={"name": "模板"})).json()["data"]
        uploaded = await client.post(
            f"/api/reverse-projects/{reverse['id']}/references",
            files={"file": ("template.png", _png(), "image/png")},
        )
        reference_id = uploaded.json()["data"]["references"][0]["id"]
        document = {
            "summary": "摘要",
            "category": "数码",
            "suitableFor": "商品图",
            "goal": "转化",
            "requiredMaterials": "白底图",
            "notSuitableFor": "无事实承诺",
            "overall": {
                "contentFlow": "首屏",
                "visualSystem": "冷色",
                "moduleStrategy": "一个问题一张图",
                "adaptationRules": "替换商品",
            },
            "modules": [{
                "id": "m1", "title": "首图", "referenceImageId": reference_id,
                "goal": "建立认知", "layout": "居中", "informationHierarchy": "标题优先",
                "typography": "左留白", "colorAndLighting": "柔光", "adaptationNotes": "替换商品",
            }],
        }
        patched = await client.patch(
            f"/api/reverse-projects/{reverse['id']}",
            json={"expectedRevision": 2, **document},
        )
        version = await client.post(
            f"/api/reverse-projects/{reverse['id']}/versions",
            json={"expectedRevision": patched.json()["data"]["revision"]},
        )
        source = await client.post(
            f"/api/projects/{business['id']}/assets",
            data={"kind": "white_background"},
            files={"file": ("product.png", _png(), "image/png")},
        )
        assert source.status_code == 201, source.text
        source_id = source.json()["data"]["id"]
        facts = {"商品名称": "蓝牙鼠标", "商品参数": "黑色，三模连接"}
        created = await client.post(
            f"/api/projects/{business['id']}/reverse-execution",
            json={
                "versionId": version.json()["data"]["id"],
                "sourceAssetId": source_id,
                "productFacts": facts,
                "outputSettings": {"outputLanguage": "英文", "model": "gpt-image-2-5", "aspectRatio": "3:4", "resolution": "高清 2K"},
            },
        )
        compiled = await client.post(
            f"/api/projects/{business['id']}/reverse-execution/compile",
            json={"expectedRevision": created.json()["data"]["revision"]},
        )
        persisted = await client.get(f"/api/projects/{business['id']}/reverse-execution")

    assert created.status_code == 201, created.text
    assert len(created.json()["data"]["tasks"]) == 1
    assert compiled.status_code == 200, compiled.text
    assert "蓝牙鼠标" in compiled.json()["data"]["tasks"][0]["promptDraft"]
    assert "黑色，三模连接" in compiled.json()["data"]["tasks"][0]["promptDraft"]
    assert persisted.json()["data"]["sourceAssetId"] == source_id
    assert persisted.json()["data"]["productFacts"] == facts
    assert persisted.json()["data"]["outputSettings"]["aspectRatio"] == "3:4"


@pytest.mark.asyncio
async def test_project_reverse_execution_api_generates_images_with_task_filter():
    generation = FakeReverseExecutionGenerationService()
    app = create_app(
        settings=Settings(_env_file=None, local_workspace_id=UUID(int=12)),
        repository=InMemoryRepository(),
        project_repository=InMemoryProjectRepository(),
        project_asset_storage=MemoryProjectAssetStorage(),
        reverse_project_repository=InMemoryReverseProjectRepository(),
        reverse_execution_generation_service=generation,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        business = (await client.post("/api/projects", json={"name": "鼠标项目"})).json()["data"]
        response = await client.post(
            f"/api/projects/{business['id']}/reverse-execution/generate",
            json={"expectedRevision": 2, "taskIds": ["task-1"], "aspectRatio": "3:4"},
        )

    assert response.status_code == 200, response.text
    assert generation.calls[0][1] == 2
    assert generation.calls[0][2]["task_ids"] == ["task-1"]
    assert response.json()["data"]["revision"] == 3
