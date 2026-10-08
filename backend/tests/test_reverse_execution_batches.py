from types import SimpleNamespace
from uuid import uuid4
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.application.reverse_execution_generation_service import ReverseExecutionGenerationService
from app.application.reverse_execution_service import ReverseExecutionService
from app.reverse_execution_repository import InMemoryReverseExecutionRepository
from backend.tests.test_reverse_execution_generation_service import (
    FakeIdentity, FakeProjectRepository, FakeAssetService, FakeEditor, FakeArchive,
)
from backend.tests.test_reverse_execution_service import FakeReverseService
from app.application.reverse_execution_parameters import ReverseExecutionParameterPlanner
from backend.tests.test_reverse_execution_parameters import FakePlanner, FakeAssets


async def harness():
    workspace, project, version = uuid4(), uuid4(), uuid4()
    repo, identity = InMemoryReverseExecutionRepository(), FakeIdentity(workspace)
    projects = FakeProjectRepository(SimpleNamespace(id=project, name="测试商品"))
    plans = ReverseExecutionService(repo, identity, projects, FakeReverseService())
    plan = await plans.generate(project, version, source_asset_id=uuid4())
    editor, assets = FakeEditor(), FakeAssetService(uuid4())
    generation = ReverseExecutionGenerationService(plan_service=plans, repository=repo,
        project_repository=projects, project_asset_service=assets,
        reverse_project_service=FakeReverseService(), image_editor=editor,
        project_archive=FakeArchive(), identity_provider=identity, provider_model="test")
    return project, plan, plans, generation, editor, assets


@pytest.mark.asyncio
async def test_new_batch_filters_watermark_from_structure_and_retry_keeps_frozen_prompt():
    project, plan, plans, generation, editor, assets = await harness()
    document=plan.document
    document["productFacts"] = {"真实品牌": "实体品牌Logo印在壳体上"}
    document["tasks"][0]["structure"]["layout"] = "纯黑背景；半透明JD.COM京东水印在主体后方；产品居中。"
    document["tasks"][0]["promptDraft"]=(
        "当前商品事实：实体品牌Logo印在壳体上\n"
        "场景与构图：纯黑背景；半透明JD.COM京东水印在主体后方；产品居中。\n"
        "信息层级：标题与参数表。\n"
        "商品以输入图片为准。"
    )
    saved=await plans.save(project,plan.revision,document,plan_id=plan.id)
    generated=await generation.generate(project,saved.revision,plan_id=plan.id)
    request=editor.requests[0]
    assert "JD.COM" not in request.prompt and "京东" not in request.prompt
    assert "纯黑背景" in request.prompt and "产品居中" in request.prompt
    assert "实体品牌Logo印在壳体上" in request.prompt
    assert "不生成参考图中的平台、店铺或版权水印" in request.prompt
    batch=(await generation.list_batches(project,plan.id))[0]
    frozen=batch.document["tasks"][0]["promptDraft"]
    assert frozen==request.prompt
    await generation.generate(project,generated.revision,plan_id=plan.id,
        batch_id=batch.id,task_ids=[batch.document["tasks"][0]["id"]])
    assert editor.requests[-1].prompt==frozen


@pytest.mark.asyncio
async def test_new_generation_recompiles_current_inputs_despite_legacy_prompt_cache():
    project, plan, plans, generation, editor, _ = await harness()
    document = deepcopy(plan.document)
    document["productFacts"] = {"商品名称": "真实新商品"}
    task = document["tasks"][0]
    task["structure"]["layout"] = "右侧真实新构图"
    task["moduleParameters"] = [{"key": "尺寸", "value": "123×67mm"}]
    task["parametersAssigned"] = True
    task["promptDraft"] = "旧完整提示词，错误商品，错误构图"
    # Simulate a pre-upgrade row without passing through the new save rules.
    legacy = await generation.repository.save(plans.workspace_id, project, plan.revision, document, plan_id=plan.id)
    generated = await generation.generate(project, legacy.revision, plan_id=plan.id, task_ids=[task["id"]])
    first_prompt = editor.requests[0].prompt
    assert "真实新商品" in first_prompt and "右侧真实新构图" in first_prompt
    assert "123×67mm" in first_prompt and "旧完整提示词" not in first_prompt
    stored = await generation.repository.get(plans.workspace_id, project, plan.id)
    assert all(not item.get("promptDraft") for item in stored.document["tasks"])
    changed = deepcopy(generated.document)
    changed["tasks"][0]["moduleParameters"] = [{"key": "尺寸", "value": "124×68mm"}]
    updated = await plans.save(project, generated.revision, changed, plan_id=plan.id)
    await generation.generate(project, updated.revision, plan_id=plan.id, task_ids=[task["id"]])
    assert "124×68mm" in editor.requests[-1].prompt and "123×67mm" not in editor.requests[-1].prompt
    batches = await generation.list_batches(project, plan.id)
    assert len(batches) == 2
    assert batches[-1].document["tasks"][0]["promptDraft"] == first_prompt


@pytest.mark.asyncio
async def test_generation_assigns_new_brief_without_frontend_compilation():
    project, plan, plans, generation, editor, _ = await harness()
    planner = FakePlanner()
    plans.parameter_planner = ReverseExecutionParameterPlanner(planner=planner, project_asset_service=FakeAssets())
    document = deepcopy(plan.document)
    document["parameterBrief"] = "静音按键，尺寸100×60mm"
    saved = await plans.save(project, plan.revision, document, plan_id=plan.id)
    generated = await generation.generate(project, saved.revision, plan_id=plan.id)
    assert "静音按键" in editor.requests[0].prompt
    assert "100×60mm" not in editor.requests[0].prompt
    assert "100×60mm" in editor.requests[1].prompt
    assert generated.document["parametersAssigned"] is True
    assert all(not task.get("promptDraft") for task in generated.document["tasks"])


@pytest.mark.asyncio
async def test_whole_generations_create_batches_and_retry_preserves_original_inputs_and_outputs():
    project, plan, plans, generation, editor, assets = await harness()
    first_plan = await generation.generate(project, plan.revision)
    second_plan = await generation.generate(project, first_plan.revision)
    batches = await generation.list_batches(project, plan.id)
    assert len(batches) == 2
    newest, first = batches
    assert newest.id != first.id
    assert [b.batch_no for b in batches] == [2, 1]
    first_prompt = first.document["tasks"][0]["promptDraft"]
    first_asset = first.document["tasks"][0]["attempts"][0]["generatedAssetId"]
    document = second_plan.document
    document["tasks"][0]["structure"]["layout"] = "修改后的新布局"
    edited = await plans.save(project, second_plan.revision, document, plan_id=plan.id)
    await generation.generate(project, edited.revision, plan_id=plan.id,
        batch_id=first.id, task_ids=[first.document["tasks"][0]["id"]])
    after = await generation.get_batch(project, first.id, plan.id)
    assert len(await generation.list_batches(project, plan.id)) == 2
    attempts = after.document["tasks"][0]["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["generatedAssetId"] == first_asset
    assert editor.requests[-1].prompt == first_prompt
    assert "修改后的新布局" not in editor.requests[-1].prompt
    assert assets.created[-1][4]["source_snapshot"]["reverseExecutionBatchId"] == str(first.id)
    assert (await plans.get(project, plan.id)).document["tasks"][0]["structure"]["layout"] == "修改后的新布局"


@pytest.mark.asyncio
async def test_invalid_task_selection_makes_no_provider_calls():
    project, plan, _, generation, editor, _ = await harness()
    with pytest.raises(Exception) as error:
        await generation.generate(project, plan.revision, task_ids=["foreign-task"])
    assert getattr(error.value, "code", None) == "REVERSE_EXECUTION_TASKS_INVALID"
    assert editor.requests == []


@pytest.mark.asyncio
async def test_archive_failure_preserves_successful_output_and_retry_failure_has_no_stale_output():
    project, plan, _, generation, editor, assets = await harness()
    async def archive_failure(**kwargs):
        raise RuntimeError("归档目录不可用")
    generation.project_archive.archive_project_output = archive_failure
    result = await generation.generate(project, plan.revision)
    batch = (await generation.list_batches(project, plan.id))[0]
    assert batch.document["status"] == "completed"
    attempt = batch.document["tasks"][0]["attempts"][0]
    assert attempt["generatedAssetId"]
    assert len(assets.created) == 2
    assert attempt["generatedPreviewUrl"]
    assert attempt["archiveError"] == "归档目录不可用"
    async def provider_failure(request):
        raise RuntimeError("provider unavailable")
    editor.edit = provider_failure
    await generation.generate(project, result.revision, batch_id=batch.id,
        task_ids=[batch.document["tasks"][0]["id"]])
    after = await generation.get_batch(project, batch.id, plan.id)
    attempts = after.document["tasks"][0]["attempts"]
    assert attempts[0]["generatedAssetId"] == attempt["generatedAssetId"]
    assert attempts[1]["status"] == "failed"
    assert "generatedAssetId" not in attempts[1]


@pytest.mark.asyncio
async def test_partial_failure_preserves_success_and_retry_appends_failed_then_successful_attempt():
    project, plan, _, generation, editor, assets = await harness()
    edit = editor.edit
    async def fail_second(request):
        if len(editor.requests) == 1:
            editor.requests.append(request)
            raise RuntimeError("测试provider失败")
        return await edit(request)
    editor.edit = fail_second
    result = await generation.generate(project, plan.revision)
    batch = (await generation.list_batches(project, plan.id))[0]
    assert batch.document["status"] == "partial"
    assert len(assets.created) == 1
    failed = batch.document["tasks"][1]
    assert failed["attempts"][0]["status"] == "failed"
    editor.edit = edit
    await generation.generate(project, result.revision, plan_id=plan.id, batch_id=batch.id, task_ids=[failed["id"]])
    recovered = await generation.get_batch(project, batch.id, plan.id)
    assert recovered.document["status"] == "completed"
    assert [a["status"] for a in recovered.document["tasks"][1]["attempts"]] == ["failed", "succeeded"]
    assert len(recovered.document["tasks"][0]["attempts"]) == 1


@pytest.mark.asyncio
async def test_concurrent_generation_of_same_plan_is_rejected_before_second_provider_call():
    project, plan, _, generation, editor, _ = await harness()
    entered, release = asyncio.Event(), asyncio.Event()
    edit = editor.edit
    async def wait(request):
        entered.set()
        await release.wait()
        return await edit(request)
    editor.edit = wait
    running = asyncio.create_task(generation.generate(project, plan.revision))
    await entered.wait()
    try:
        batch = (await generation.list_batches(project, plan.id))[0]
        assert batch.document["status"] == "running"
        with pytest.raises(Exception) as error:
            await generation.generate(project, plan.revision)
        assert error.value.code == "REVERSE_BATCH_RUNNING"
    finally:
        release.set()
        await running


@pytest.mark.asyncio
async def test_expired_running_batch_becomes_retryable_without_losing_completed_attempts():
    project, plan, _, generation, _, _ = await harness()
    result = await generation.generate(project, plan.revision)
    batch = (await generation.list_batches(project, plan.id))[0]
    document = batch.document
    original = document["tasks"][0]["attempts"][0]["generatedAssetId"]
    document["status"] = "running"
    document["leaseExpiresAt"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    task = document["tasks"][1]
    task["status"] = "generating"
    task["attempts"].append({"id": "interrupted", "number": 2, "status": "generating"})
    await generation.batch_repository.save(batch, document)
    recovered = (await generation.list_batches(project, plan.id))[0]
    assert recovered.document["status"] == "partial"
    assert recovered.document["tasks"][0]["attempts"][0]["generatedAssetId"] == original
    assert recovered.document["tasks"][1]["attempts"][-1]["status"] == "failed"
    await generation.generate(project, result.revision, batch_id=batch.id, task_ids=[task["id"]])
