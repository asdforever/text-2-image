from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.application.hero_generation_ports import ImageEditResult
from app.application.reverse_execution_generation_service import ReverseExecutionGenerationService
from app.application.reverse_execution_service import ReverseExecutionService
from app.reverse_execution_repository import InMemoryReverseExecutionRepository
from app.storage import StoredObject


class FakeIdentity:
    def __init__(self, workspace_id):
        self.workspace_id = workspace_id

    def get_context(self):
        return SimpleNamespace(workspace_id=self.workspace_id)


class FakeProjectRepository:
    def __init__(self, project):
        self.project = project

    async def get_project(self, project_id, workspace_id):
        return self.project if self.project.id == project_id else None


class FakeReverseProjectService:
    def __init__(self, version, storage):
        self.version = version
        self.storage = storage

    async def get_version(self, version_id):
        return self.version


class FakeAssetService:
    def __init__(self, source_asset_id):
        self.source_asset_id = source_asset_id
        self.created = []
        self.preview_ids = []

    async def get_selections(self, project_id):
        return {"source": self.source_asset_id}

    async def get_asset_details(self, project_id, asset_id):
        return SimpleNamespace(id=asset_id), SimpleNamespace(
            original_filename="product.png", media_type="image/png"
        )

    async def get_preview(self, project_id, asset_id):
        self.preview_ids.append(asset_id)
        return StoredObject("product.png", b"product", "image/png")

    async def create_generated_asset(self, project_id, body, declared_mime, filename, **kwargs):
        asset = SimpleNamespace(id=uuid4())
        self.created.append((project_id, body, declared_mime, filename, kwargs))
        return asset


class FakeEditor:
    def __init__(self):
        self.requests = []

    async def edit(self, request):
        self.requests.append(request)
        return ImageEditResult(b"result", "image/png", {"ok": True})


class FakeArchive:
    def __init__(self):
        self.calls = []

    async def archive_project_output(self, **kwargs):
        self.calls.append(kwargs)


class FakeConnections:
    async def snapshot(self, model):
        assert model == "chosen-model"
        return {"modelName": "real-image-model", "connectionId": "chosen-connection", "aspectRatios": ["3:4"], "resolutions": ["2K"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("compile_first", [True, False])
async def test_generation_uses_only_product_and_module_prompts_and_archives_each_task(compile_first):
    workspace_id = uuid4()
    project_id = uuid4()
    version_id = uuid4()
    reference_ids = ["ref-1", "ref-2"]
    reverse_storage = {
        "template-1": StoredObject("template-1", b"template-1", "image/png"),
        "template-2": StoredObject("template-2", b"template-2", "image/png"),
    }
    version = SimpleNamespace(
        id=version_id,
        reverse_project_id=uuid4(),
        document={
            "references": [
                {"id": "ref-1", "storageKey": "template-1", "filename": "a.png", "mimeType": "image/png"},
                {"id": "ref-2", "storageKey": "template-2", "filename": "b.png", "mimeType": "image/png"},
            ],
            "modules": [
                {"id": "module-1", "referenceImageId": "ref-1", "layout": "浅木办公桌面", "colorAndLighting": "自然侧光"},
                {"id": "module-2", "referenceImageId": "ref-2", "layout": "深色电竞桌面", "typography": "左侧短标题"},
            ],
        },
    )
    plan_repo = InMemoryReverseExecutionRepository()
    identity = FakeIdentity(workspace_id)
    project_repo = FakeProjectRepository(SimpleNamespace(id=project_id, name="鼠标项目"))
    reverse_service = FakeReverseProjectService(version, _MemoryStorage(reverse_storage))
    plan_service = ReverseExecutionService(plan_repo, identity, project_repo, reverse_service)
    selected_asset_id = uuid4()
    product_facts = {"商品名称": "蓝牙鼠标", "商品参数": "黑色，三模连接", "核心卖点": "轻量便携"}
    created = await plan_service.generate(project_id, version_id, source_asset_id=selected_asset_id, product_facts=product_facts,
        output_settings={"outputLanguage": "英文", "model": "chosen-model", "aspectRatio": "3:4", "resolution": "高清 2K"})
    if compile_first:
        created = await plan_service.compile(project_id, created.revision)

    assets = FakeAssetService(uuid4())
    editor = FakeEditor()
    archive = FakeArchive()
    service = ReverseExecutionGenerationService(
        plan_service=plan_service,
        repository=plan_repo,
        project_repository=project_repo,
        project_asset_service=assets,
        reverse_project_service=reverse_service,
        image_editor=editor,
        project_archive=archive,
        identity_provider=identity,
        provider_model="test-model",
        model_connections=FakeConnections(),
    )

    result = await service.generate(project_id, created.revision)

    assert len(editor.requests) == 2
    assert [item.image_bytes for item in editor.requests[0].image_inputs] == [b"product"]
    assert [item.image_bytes for item in editor.requests[1].image_inputs] == [b"product"]
    assert reverse_service.storage.read_keys == []
    assert "浅木办公桌面" in editor.requests[0].prompt
    assert "自然侧光" in editor.requests[0].prompt
    assert "深色电竞桌面" in editor.requests[1].prompt
    assert "左侧短标题" in editor.requests[1].prompt
    assert "蓝牙鼠标" in editor.requests[0].prompt
    assert all("黑色，三模连接" in request.prompt and "轻量便携" in request.prompt for request in editor.requests)
    assert all(request.aspect_ratio == "3:4" and request.resolution == "高清 2K" for request in editor.requests)
    assert all(request.model_connection["modelName"] == "real-image-model" for request in editor.requests)
    assert all("英文" in request.prompt for request in editor.requests)
    assert assets.preview_ids == [selected_asset_id]
    assert all(item[4]["source_asset_id"] == selected_asset_id for item in assets.created)
    assert assets.created[0][4]["source_snapshot"]["moduleId"] == "module-1"
    assert result.document["productFacts"] == product_facts
    assert result.document["sourceAssetId"] == str(selected_asset_id)
    assert len(assets.created) == 2
    assert len(archive.calls) == 2
    assert all(call["product_type"] == "detail" for call in archive.calls)
    assert all(call["config_snapshot"]["modelId"] == "chosen-model" and call["config_snapshot"]["outputLanguage"] == "英文" for call in archive.calls)
    assert all(task["status"] == "succeeded" for task in result.document["tasks"])
    assert all(task.get("generatedAssetId") for task in result.document["tasks"])
    assert [task["referenceImageId"] for task in result.document["tasks"]] == reference_ids


@dataclass
class _MemoryStorage:
    objects: dict[str, StoredObject]

    def __post_init__(self):
        self.read_keys = []

    async def get(self, key):
        self.read_keys.append(key)
        return self.objects.get(key)
