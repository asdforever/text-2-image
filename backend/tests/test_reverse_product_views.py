from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from PIL import Image
import pytest

from app.application.hero_generation_ports import ImageEditResult
from app.application.project_asset_service import ProjectAssetService
from app.application.reverse_execution_service import ReverseExecutionService
from app.application.reverse_execution_generation_service import ReverseExecutionGenerationService
from app.core.errors import AppError
from app.core.identity import IdentityContext, LocalSingleUserIdentityProvider
from app.project_repository import InMemoryProjectRepository
from app.project_storage import MemoryProjectAssetStorage
from app.reverse_execution_repository import InMemoryReverseExecutionRepository
from app.storage import StoredObject


def png(color):
    out = BytesIO(); Image.new("RGB", (8, 8), color).save(out, "PNG"); return out.getvalue()


async def fixture():
    identity = LocalSingleUserIdentityProvider(IdentityContext(uuid4(), uuid4(), "owner"))
    projects, storage = InMemoryProjectRepository(), MemoryProjectAssetStorage()
    project = await projects.create_project("多视角鼠标", identity.get_context().workspace_id)
    assets = ProjectAssetService(projects, storage, identity)
    images = [await assets.upload_asset(project.id, "white_background", png(color), "image/png", f"{color}.png") for color in ("red", "blue", "green")]
    version = SimpleNamespace(id=uuid4(), document={"references": [{"id": "ref", "filename": "对标.png"}], "modules": [{"id": "module", "referenceImageId": "ref", "layout": "左侧俯拍商品"}]})
    class Reverse:
        async def get_version(self, version_id): return version
    reverse = Reverse()
    plans = ReverseExecutionService(InMemoryReverseExecutionRepository(), identity, projects, reverse)
    class Editor:
        supports_multiple_source_images = True
        def __init__(self): self.requests = []
        async def edit(self, request):
            self.requests.append(request)
            return ImageEditResult(png("white"), "image/png", {})
    editor = Editor()
    generation = ReverseExecutionGenerationService(plan_service=plans, repository=plans.repository, project_repository=projects, project_asset_service=assets, reverse_project_service=reverse, image_editor=editor, project_archive=None, identity_provider=identity, provider_model="test")
    return project, images, version, plans, generation, editor, projects, assets


@pytest.mark.asyncio
async def test_primary_and_auxiliary_views_are_sent_and_old_batch_retry_keeps_frozen_inputs():
    project, images, version, plans, generation, editor, *_ = await fixture()
    plan = await plans.generate(project.id, version.id, source_asset_id=images[0].id, auxiliary_source_asset_ids=[images[1].id])
    preview = await plans.compile(project.id, plan.revision, plan_id=plan.id)
    assert "同一商品" in preview.document["tasks"][0]["promptDraft"]
    plan = await generation.generate(project.id, preview.revision, plan_id=plan.id)
    assert [item.image_bytes for item in editor.requests[0].image_inputs] == [png("red"), png("blue")]
    assert "第1张" in editor.requests[0].prompt and "同一商品" in editor.requests[0].prompt
    batch = (await generation.list_batches(project.id, plan.id))[0]
    assert batch.document["auxiliarySourceAssetIds"] == [str(images[1].id)]
    assert len(batch.document["productImages"]) == 2
    document = deepcopy(plan.document)
    document["sourceAssetId"] = str(images[2].id)
    document["auxiliarySourceAssetIds"] = [str(images[0].id)]
    plan = await plans.save(project.id, plan.revision, document, plan_id=plan.id)
    await generation.generate(project.id, plan.revision, plan_id=plan.id, batch_id=batch.id, task_ids=[plan.document["tasks"][0]["id"]])
    assert [item.image_bytes for item in editor.requests[1].image_inputs] == [png("red"), png("blue")]


@pytest.mark.asyncio
async def test_foreign_auxiliary_asset_is_rejected_before_generating():
    project, images, version, plans, generation, editor, projects, assets = await fixture()
    foreign = await projects.create_project("其他商品", plans.workspace_id)
    image = await assets.upload_asset(foreign.id, "source", png("black"), "image/png", "foreign.png")
    with pytest.raises(AppError):
        await plans.generate(project.id, version.id, source_asset_id=images[0].id, auxiliary_source_asset_ids=[image.id])
    assert not editor.requests


@pytest.mark.asyncio
async def test_changed_auxiliary_bytes_cannot_silently_replace_batch_input():
    project, images, version, plans, generation, editor, _, assets = await fixture()
    plan = await plans.generate(project.id, version.id, source_asset_id=images[0].id, auxiliary_source_asset_ids=[images[1].id])
    plan = await generation.generate(project.id, plan.revision, plan_id=plan.id)
    batch = (await generation.list_batches(project.id, plan.id))[0]
    _, obj = await assets.get_asset_details(project.id, images[1].id)
    await assets.storage.put(StoredObject(obj.storage_key, png("black"), "image/png"))
    with pytest.raises(AppError) as error:
        await generation.generate(project.id, plan.revision, plan_id=plan.id, batch_id=batch.id, task_ids=[plan.document["tasks"][0]["id"]])
    assert error.value.code == "REVERSE_PRODUCT_IMAGES_CHANGED"
    assert len(editor.requests) == 1


@pytest.mark.asyncio
async def test_auxiliary_selection_is_deduplicated_and_removes_primary():
    project, images, version, plans, *_ = await fixture()
    plan = await plans.generate(project.id, version.id, source_asset_id=images[0].id, auxiliary_source_asset_ids=[images[0].id, images[1].id, images[1].id])
    assert plan.document["auxiliarySourceAssetIds"] == [str(images[1].id)]
    document = deepcopy(plan.document)
    document["auxiliarySourceAssetIds"] = [str(uuid4()) for _ in range(5)]
    with pytest.raises(AppError) as error:
        await plans.save(project.id, plan.revision, document, plan_id=plan.id)
    assert error.value.code == "REVERSE_PRODUCT_IMAGES_INVALID"


@pytest.mark.asyncio
async def test_parameter_planning_reads_all_current_product_views():
    import json
    from app.application.reverse_execution_parameters import ReverseExecutionParameterPlanner
    project, images, version, plans, _, _, _, assets = await fixture()
    class Planner:
        def __init__(self): self.requests = []
        async def plan_modules(self, request):
            self.requests.append(request)
            tasks = json.loads(request.user_prompt)["tasks"]
            return {"summary": "商品细节", "tasks": [{"taskId": task["id"], "moduleParameters": []} for task in tasks]}
    planner = Planner()
    plans.parameter_planner = ReverseExecutionParameterPlanner(planner=planner, project_asset_service=assets)
    plan = await plans.generate(project.id, version.id, source_asset_id=images[0].id, auxiliary_source_asset_ids=[images[1].id])
    await plans.assign_parameters(project.id, plan.revision, plan_id=plan.id)
    assert planner.requests[0].image_inputs == [png("red"), png("blue")]
    assert "同一商品" in planner.requests[0].system_prompt


@pytest.mark.asyncio
async def test_generation_override_assigns_parameters_with_new_view_selection():
    project, images, version, plans, generation, editor, *_ = await fixture()
    class Planner:
        def __init__(self): self.documents = []
        async def assign(self, project_id, document):
            self.documents.append(deepcopy(document))
            return {"summary": "视角", "tasks": [{"taskId": task["id"], "moduleParameters": []} for task in document["tasks"]], "warnings": [], "promptModelConnection": None}
    planner = Planner()
    plans.parameter_planner = planner
    plan = await plans.generate(project.id, version.id, source_asset_id=images[0].id, auxiliary_source_asset_ids=[images[1].id], parameter_brief="保持真实结构")
    await generation.generate(project.id, plan.revision, plan_id=plan.id, source_asset_id=images[1].id, auxiliary_source_asset_ids=[images[2].id])
    assert planner.documents[0]["sourceAssetId"] == str(images[1].id)
    assert planner.documents[0]["auxiliarySourceAssetIds"] == [str(images[2].id)]
    assert [item.image_bytes for item in editor.requests[0].image_inputs] == [png("blue"), png("green")]
