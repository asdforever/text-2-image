from copy import deepcopy

import pytest

from backend.app.core.errors import AppError
from backend.tests.test_hero_generation_confirm_service import _fixture as hero_fixture, _compile_input
from backend.tests.test_batch_generation_compile_service import _fixture as batch_fixture, _input
from backend.tests.test_suite_planning_service import _fixture as suite_fixture
from backend.tests.test_canvas_generation import fixture as canvas_fixture
from backend.tests.test_style_harmonization import fixture as style_fixture


CONNECTION = {"connectionId": "connection-a", "baseUrl": "https://a.example/v1", "modelName": "selected-image-model", "protocol": "openai_images", "modelId": "gpt-image-2-5"}


class Connections:
    def __init__(self):
        self.current = deepcopy(CONNECTION)
        self.selections = []

    async def snapshot(self, model=None):
        self.selections.append(deepcopy(model))
        return deepcopy(self.current)


async def compilation(kind, *, aspect_ratios=None):
    from backend.app.application.suite_planning_service import SuitePlanCompilationInput, SuitePlanModuleInput
    fixture = await {"hero": hero_fixture, "batch": batch_fixture, "suite": suite_fixture}[kind]()
    fixture.service.model_connections = Connections()
    published = deepcopy(await fixture.config.get_published())
    model = next(item for item in published.content["models"] if item["id"] == "gpt-image-2-5")
    model.update(provider="兼容接口", connectionId="connection-a", aspectRatios=aspect_ratios or ["1:1"])
    async def get_published():
        return published
    fixture.config.get_published = get_published
    if kind == "hero":
        run = lambda: fixture.service.compile_prompt(fixture.project.id, _compile_input(fixture.source.id), "connection")
    elif kind == "batch":
        run = lambda: fixture.service.compile_prompt_batch(fixture.project_id, _input(fixture.source_asset_id), "connection")
    else:
        request = SuitePlanCompilationInput(fixture.source_asset_ids, "taobao", "gpt-image-2-5", "minimal", "1:1", "标准 1K", "中文", [SuitePlanModuleInput("suite-hero", 1)])
        run = lambda: fixture.service.compile_plan(fixture.project_id, request, "connection")
    return fixture, run


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["hero", "batch", "suite"])
async def test_compilation_freezes_selected_connection_with_custom_provider_label(kind):
    fixture, run = await compilation(kind)
    task = await run()
    if kind == "batch":
        detail = await fixture.repository.get_batch_detail(task.id, fixture.workspace_id)
        selections = [module.snapshot["selection"] for module in detail.module_tasks]
    else:
        selections = [task.snapshot["selection"]]
    assert all(selection["modelConnection"] == CONNECTION for selection in selections)
    assert all(selection["providerModel"] == "selected-image-model" for selection in selections)
    assert fixture.service.model_connections.selections[0]["connectionId"] == "connection-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["hero", "batch", "suite"])
async def test_compilation_rejects_ratio_outside_selected_model_capabilities(kind):
    fixture, run = await compilation(kind, aspect_ratios=["3:4"])
    with pytest.raises(AppError) as caught:
        await run()
    assert caught.value.code == "GENERATION_CONFIG_SELECTION_INVALID"
    if kind != "hero":
        assert fixture.compiler.requests == []


@pytest.mark.asyncio
async def test_hero_confirmation_uses_frozen_connection_after_catalog_changes():
    fixture, run = await compilation("hero")
    task = await run()
    fixture.service.model_connections.current["connectionId"] = "connection-b"
    result = await fixture.service.confirm_generation(fixture.project.id, task.id, task_prompt=None, idempotency_key="confirm")
    assert result.status == "succeeded"
    assert fixture.editor.requests[-1].model_connection == CONNECTION


@pytest.mark.asyncio
async def test_batch_worker_passes_connection_from_compiled_module():
    from backend.app.application.batch_generation_confirmation_service import BatchGenerationConfirmationService
    from backend.app.application.batch_generation_worker import BatchGenerationWorker
    from backend.app.application.project_asset_service import ProjectAssetService
    from backend.tests.test_batch_generation_worker import SuccessEditor
    fixture, run = await compilation("batch")
    batch = await run()
    await BatchGenerationConfirmationService(fixture.repository, fixture.service.identity_provider).confirm_batch(fixture.project_id, batch.id, {task.module_key: task.compiled_task_prompt for task in (await fixture.repository.get_batch_detail(batch.id, fixture.workspace_id)).module_tasks}, "confirm")
    fixture.service.model_connections.current["connectionId"] = "connection-b"
    editor = SuccessEditor()
    worker = BatchGenerationWorker(repository=fixture.repository, project_repository=fixture.projects, project_storage=fixture.storage, project_asset_service=ProjectAssetService(fixture.projects, fixture.storage, fixture.service.identity_provider), image_editor=editor, worker_id="connection-worker")
    assert await worker.run_once(limit=1) == 1
    assert editor.requests[0].model_connection == CONNECTION


@pytest.mark.asyncio
async def test_suite_worker_reads_frozen_connection_from_batch_snapshot():
    from backend.app.application.batch_generation_worker import BatchGenerationWorker
    from backend.app.application.project_asset_service import ProjectAssetService
    from backend.tests.test_batch_generation_worker import _suite_worker_fixture, MultiImageEditor
    fixture, _, _, _ = await _suite_worker_fixture(model_connection=deepcopy(CONNECTION))
    editor = MultiImageEditor()
    worker = BatchGenerationWorker(repository=fixture.repository, project_repository=fixture.projects, project_storage=fixture.storage, project_asset_service=ProjectAssetService(fixture.projects, fixture.storage, fixture.service.identity_provider), image_editor=editor, worker_id="suite-connection-worker")
    assert await worker.run_once(limit=1) == 1
    assert editor.requests[0].model_connection == CONNECTION
    assert len(editor.requests[0].ordered_image_inputs()) == 2


@pytest.mark.asyncio
async def test_canvas_regeneration_keeps_connection_when_environment_model_changes():
    service, project, _, _, _, step, editor, archive = await canvas_fixture()
    step["parameters"].update(modelConnection=deepcopy(CONNECTION), providerModel="selected-image-model")
    service.provider_model = "different-environment-model"
    revision = await service.submit(project.id, step["id"], "original", "新任务", None, "connection")
    await service.execute(project.id, step["id"], revision["id"])
    assert editor.requests[0].model_connection == CONNECTION
    assert archive.items[0]["config_snapshot"]["providerModel"] == "selected-image-model"


@pytest.mark.asyncio
async def test_canvas_restores_preset_connection_without_replacing_it_with_current_default():
    service, project, _, _, _, step, editor, _ = await canvas_fixture()
    service.model_connections = Connections()
    step["parameters"].update(modelPreset={"id": "old-preset", "connectionId": "connection-a"}, providerModel="historical-model")
    revision = await service.submit(project.id, step["id"], "original", "新任务", None, "preset")
    service.model_connections.current["connectionId"] = "connection-b"
    await service.execute(project.id, step["id"], revision["id"])
    assert editor.requests[0].model_connection == CONNECTION
    assert service.model_connections.selections == [{"id": "old-preset", "connectionId": "connection-a"}]


@pytest.mark.asyncio
async def test_canvas_freezes_environment_for_legacy_history_without_model_connection():
    service, project, _, _, _, step, editor, _ = await canvas_fixture()
    service.model_connections = Connections()
    revision = await service.submit(project.id, step["id"], "original", "新任务", None, "legacy")
    service.model_connections.current["connectionId"] = "connection-b"
    await service.execute(project.id, step["id"], revision["id"])
    assert editor.requests[0].model_connection == CONNECTION
    assert service.model_connections.selections == [{"connectionId": "environment"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", [None, "chosen"])
async def test_style_task_freezes_default_connection_before_execution(model_id):
    service, _, project, _, _, old, editor, archive = await style_fixture()
    connections = Connections()
    service.model_connections = connections
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "暖色", **({"modelId": model_id} if model_id else {})}, "connection")
    connections.current["connectionId"] = "connection-b"
    await service.execute(project.id, job["id"])
    assert editor.requests[0].model_connection == CONNECTION
    assert archive.items[0]["config_snapshot"]["modelConnection"] == CONNECTION
    assert connections.selections == [model_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{"ratio": "1:1", "size": "1K"}, {"generationParams": {"ratio": "1:1", "modelId": "chosen"}}])
async def test_image_edit_freezes_default_or_selected_connection_and_regeneration_retains_it(config):
    from backend.app.application.image_editing_service import ImageEditingService
    from backend.app.application.image_editing_worker import ImageEditingWorker
    from backend.app.application.canvas_lineage import canvas_generation_steps
    service, project, source, _, _, _, editor, _ = await canvas_fixture()
    connections = Connections()
    edits = ImageEditingService(None, service.projects, service.identity)
    edits.model_connections = connections
    session = await edits.create_session(project.id, source.id)
    task = await edits.submit_session(session.id, prompt_snapshot={"summary": "白色背景"}, config_snapshot=config)
    connections.current["connectionId"] = "connection-b"
    worker = ImageEditingWorker(edits.repository, service.projects, service.storage, edits, editor)
    editor.fail = True
    await worker.process_task(task.id)
    assert task.status == "failed"
    editor.fail = False
    await edits.retry_attempt(task.attempts[0].id)
    await worker.process_task(task.id)
    again = await edits.regenerate_task(task.id)
    await worker.process_task(again.id)
    assert task.status == again.status == "succeeded"
    assert [request.model_connection for request in editor.requests] == [CONNECTION, CONNECTION, CONNECTION]
    assert connections.selections == [config.get("generationParams", {}).get("modelId")]
    steps = await canvas_generation_steps(project.id, service.scope, [], None, [task])
    assert steps[0]["parameters"]["modelConnection"] == CONNECTION


@pytest.mark.asyncio
async def test_style_selects_only_supported_model_dimensions():
    service, _, project, _, _, old, editor, _ = await style_fixture()
    connections = Connections()
    connections.current.update(aspectRatios=["3:4"], resolutions=["2K"])
    service.model_connections = connections
    job = await service.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "暖色"}, "limited")
    await service.execute(project.id, job["id"])
    assert editor.requests[0].aspect_ratio == "3:4"
    assert editor.requests[0].resolution == "高清 2K"


@pytest.mark.asyncio
async def test_image_edit_rejects_unsupported_dimensions_before_creating_task():
    from backend.app.application.image_editing_service import ImageEditingService
    service, project, source, _, _, _, _, _ = await canvas_fixture()
    edits = ImageEditingService(None, service.projects, service.identity)
    edits.model_connections = Connections()
    edits.model_connections.current.update(aspectRatios=["1:1"], resolutions=["标准 1K"])
    session = await edits.create_session(project.id, source.id)
    with pytest.raises(AppError, match="比例"):
        await edits.submit_session(session.id, prompt_snapshot={"summary": "白色背景"}, config_snapshot={"ratio": "16:9"})
    task = await edits.submit_session(session.id, prompt_snapshot={"summary": "白色背景"}, config_snapshot={"ratio": "1:1", "size": "1K"})
    assert task.config_snapshot["modelConnection"]["resolutions"] == ["标准 1K"]


@pytest.mark.asyncio
async def test_external_model_selection_cannot_inject_unpublished_connection():
    from backend.app.application.image_editing_service import ImageEditingService
    from backend.app.application.library_services import SqlAlchemyTestRunService
    from uuid import uuid4
    service, project, source, _, _, _, _, _ = await canvas_fixture()
    edits = ImageEditingService(None, service.projects, service.identity)
    edits.model_connections = Connections()
    session = await edits.create_session(project.id, source.id)
    injected = {"connectionId": "unpublished"}
    with pytest.raises(AppError, match="已发布"):
        await edits.submit_session(session.id, prompt_snapshot={"summary": "白色背景"}, config_snapshot={"modelId": injected})
    tests = SqlAlchemyTestRunService(None)
    tests.model_connections = Connections()
    with pytest.raises(AppError, match="已发布"):
        await tests.create_run({"promptVersionId": str(uuid4()), "inputText": "商品", "modelId": injected})
    styling, _, project, _, _, old, _, _ = await style_fixture()
    styling.model_connections = Connections()
    with pytest.raises(AppError, match="已发布"):
        await styling.submit(project.id, {"assetIds": [str(old.id)], "mode": "custom", "prompt": "暖色", "modelId": injected}, "injected")
    assert edits.model_connections.selections == tests.model_connections.selections == styling.model_connections.selections == []
