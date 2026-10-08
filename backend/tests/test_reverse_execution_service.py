from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.application.reverse_execution_service import ReverseExecutionService
from app.reverse_execution_repository import InMemoryReverseExecutionRepository


class FakeIdentity:
    def __init__(self, workspace_id):
        self.workspace_id = workspace_id

    def get_context(self):
        return SimpleNamespace(workspace_id=self.workspace_id)


class FakeProjectRepository:
    async def get_project(self, project_id, workspace_id):
        return SimpleNamespace(id=project_id, workspace_id=workspace_id, name="当前商品")


class FakeReverseService:
    async def get_version(self, version_id):
        return SimpleNamespace(
            id=version_id,
            reverse_project_id=uuid4(),
            version_no=2,
            document={
                "references": [
                    {"id": "ref-1", "ordinal": 1, "filename": "a.png", "previewUrl": "/a"},
                    {"id": "ref-2", "ordinal": 2, "filename": "b.png", "previewUrl": "/b"},
                ],
                "modules": [
                    {
                        "id": "module-1", "title": "首图", "referenceImageId": "ref-1",
                        "goal": "建立认知", "layout": "居中", "informationHierarchy": "品牌优先",
                        "typography": "左侧留白", "colorAndLighting": "柔光", "adaptationNotes": "替换商品",
                    }
                ],
            },
        )


@pytest.mark.asyncio
async def test_service_generates_ordered_plan_and_compiles_each_task():
    workspace_id = uuid4()
    repository = InMemoryReverseExecutionRepository()
    service = ReverseExecutionService(repository, FakeIdentity(workspace_id), FakeProjectRepository(), FakeReverseService())
    project_id = uuid4()
    version_id = UUID("22222222-2222-2222-2222-222222222222")

    created = await service.generate(project_id, version_id)
    assert [task["referenceImageId"] for task in created.document["tasks"]] == ["ref-1", "ref-2"]

    compiled = await service.compile(
        project_id,
        expected_revision=created.revision,
        product_facts={"商品名称": "蓝牙鼠标"},
    )
    assert compiled.revision == 2
    assert all(task["promptDraft"] for task in compiled.document["tasks"])
    assert "蓝牙鼠标" in compiled.document["tasks"][0]["promptDraft"]
    assert compiled.document["productFacts"] == {"商品名称": "蓝牙鼠标"}
    recompiled = await service.compile(project_id, compiled.revision)
    assert "蓝牙鼠标" in recompiled.document["tasks"][0]["promptDraft"]

    changed = recompiled.document
    changed["productFacts"] = {"商品名称": "有线鼠标", "商品参数": "USB 接口"}
    saved = await service.save(project_id, recompiled.revision, changed)
    assert all(not task["promptDraft"] for task in saved.document["tasks"])
    assert all(task["status"] == "draft" for task in saved.document["tasks"])


@pytest.mark.asyncio
async def test_compiled_preview_and_client_prompt_are_not_persisted_in_plan():
    workspace_id, project_id = uuid4(), uuid4()
    repository = InMemoryReverseExecutionRepository()
    service = ReverseExecutionService(repository, FakeIdentity(workspace_id), FakeProjectRepository(), FakeReverseService())
    created = await service.generate(project_id, uuid4())
    preview = await service.compile(project_id, created.revision, {"商品名称": "真实鼠标"})
    assert "真实鼠标" in preview.document["tasks"][0]["promptDraft"]
    persisted = await repository.get(workspace_id, project_id, created.id)
    assert all(not task.get("promptDraft") for task in persisted.document["tasks"])
    preview.document["tasks"][0]["promptDraft"] = "旧的完整提示词"
    await service.save(project_id, preview.revision, preview.document, plan_id=created.id)
    persisted = await repository.get(workspace_id, project_id, created.id)
    assert all(not task.get("promptDraft") for task in persisted.document["tasks"])
