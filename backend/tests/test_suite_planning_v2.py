import asyncio
import json
from hashlib import sha256
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.application.suite_planning_confirmation_service import SuitePlanningConfirmationService
from backend.app.application.suite_planning_service import (
    SuitePlanCompilationInput, SuitePlanModuleInput, SuitePlanModuleUpdateInput,
)
from backend.app.core.errors import AppError
from backend.tests.test_module_planning_v2 import _result_payload
from backend.tests.test_suite_planning_service import _fixture


async def fixture_v2():
    fixture = await _fixture()
    fixture.calls = []

    async def compile_module(request):
        fixture.calls.append(request)
        result = _result_payload()
        result["copySummary"] = request.module_parameters[0]["value"]
        return result

    async def no_style_call(_request):
        raise AssertionError("V2 must not call a style model")

    fixture.service.planner_compiler.compile = compile_module
    fixture.request = SuitePlanCompilationInput(
        fixture.source_asset_ids, "taobao", "gpt-image-2-5", "minimal", "3:4", "标准 1K", "中文",
        [SuitePlanModuleInput("suite-hero", 1, [{"key": "本图任务", "value": "整体外观"}], "overall"),
         SuitePlanModuleInput("suite-hero", 1, [{"key": "本图任务", "value": "局部结构"}], "detail")],
        user_notes="不要新增配件",
    )
    return fixture


@pytest.mark.asyncio
async def test_suite_v2_one_call_per_task_and_frozen_structure_with_full_outline():
    f = await fixture_v2()
    plan = await f.service.compile_plan(f.project_id, f.request, "v2")
    detail = await f.service.get_plan(f.project_id, plan.id)
    assert plan.status == "awaiting_confirmation"
    assert plan.snapshot["plannerVersion"] == "v2"
    assert len(f.calls) == 2
    assert [row.module_key for row in detail.modules] == ["overall", "detail"]
    assert detail.modules[0].compiled_task_prompt.strip()
    assert detail.modules[1].compiled_task_prompt.strip()
    for call, row in zip(f.calls, detail.modules):
        assert call.planner_version == "v2"
        context = json.loads(call.user_prompt)
        assert context["currentTaskId"] == row.module_key
        assert [task["taskId"] for task in context["tasks"]] == ["overall", "detail"]
        assert context["userNotes"] == "不要新增配件"
        assert len(call.image_inputs) == 2
        assert row.prompt_snapshot["modulePlanning"]["result"]["copySummary"]
        assert row.prompt_snapshot["constraints"]["style"]["source"] == "style_seed_v2"
        assert "stylePlanning" not in row.prompt_snapshot
    replay = await f.service.compile_plan(f.project_id, f.request, "v2")
    assert replay.id == plan.id
    assert len(f.calls) == 2


@pytest.mark.asyncio
async def test_suite_v2_confirm_uses_saved_plan_and_rejects_override_after_rollback():
    f = await fixture_v2()
    plan = await f.service.compile_plan(f.project_id, f.request, "v2-confirm")
    detail = await f.service.get_plan(f.project_id, plan.id)
    prompts = {row.module_key: row.compiled_task_prompt for row in detail.modules}
    confirm = SuitePlanningConfirmationService(
        plan_repository=f.plans, batch_repository=f.batches, identity_provider=f.service.identity_provider,
    )
    with pytest.raises(AppError) as error:
        await confirm.confirm_plan(f.project_id, plan.id, expected_plan_revision=plan.revision,
                                   module_task_prompts={**prompts, "overall": "修改背景与比例"}, idempotency_key="invalid")
    assert error.value.code == "V2_PROMPT_READ_ONLY"
    batch = await confirm.confirm_plan(f.project_id, plan.id, expected_plan_revision=plan.revision,
                                      module_task_prompts=prompts, idempotency_key="confirm")
    generated = await f.batches.get_batch_detail(batch.id, f.workspace_id)
    assert batch.snapshot["plannerVersion"] == "v2"
    for row in generated.module_tasks:
        assert row.final_prompt_sha256 == sha256(row.final_prompt.encode()).hexdigest()
        assert row.confirmed_task_prompt == prompts[row.module_key]
    replay = await confirm.confirm_plan(f.project_id, plan.id, expected_plan_revision=plan.revision,
                                       module_task_prompts=prompts, idempotency_key="confirm")
    assert replay.id == batch.id
    assert len(f.calls) == 2


@pytest.mark.asyncio
async def test_suite_v2_edit_cannot_desynchronize_frozen_plan():
    f = await fixture_v2()
    plan = await f.service.compile_plan(f.project_id, f.request, "v2-edit")
    detail = await f.service.get_plan(f.project_id, plan.id)
    for patch in ({"current_task_prompt": "重写最终提示词"}, {"module_parameters": [{"key": "功率", "value": "1000W"}]}, {"visual_direction": "红色背景"}):
        with pytest.raises(AppError) as error:
            await f.service.update_module(f.project_id, plan.id, SuitePlanModuleUpdateInput(
                detail.modules[0].id, detail.plan.revision, detail.modules[0].revision, **patch,
            ))
        assert error.value.code == "V2_PROMPT_READ_ONLY"
    assert (await f.service.get_plan(f.project_id, plan.id)).modules == detail.modules


@pytest.mark.asyncio
async def test_suite_v2_malformed_result_fails_and_keeps_earlier_result():
    f = await fixture_v2()
    calls = 0
    async def compile_module(_request):
        nonlocal calls
        calls += 1
        return _result_payload() if calls == 1 else {"taskPrompt": "旧格式"}
    f.service.planner_compiler.compile = compile_module
    with pytest.raises(AppError) as error:
        await f.service.compile_plan(f.project_id, f.request, "bad")
    assert error.value.code == "PLANNING_COMPILER_INVALID_RESPONSE"
    plan = await f.plans.get_by_compile_idempotency(f.workspace_id, "bad")
    assert plan.status == "failed"
    detail = await f.service.get_plan(f.project_id, plan.id)
    assert detail.modules[0].prompt_snapshot["modulePlanning"]["result"] == _result_payload()
    assert "modulePlanning" not in detail.modules[1].prompt_snapshot
    assert (await f.service.compile_plan(f.project_id, f.request, "bad")).id == plan.id
    assert calls == 2


@pytest.mark.asyncio
async def test_suite_v2_concurrent_replay_does_not_duplicate_module_calls():
    f = await fixture_v2()
    entered, release = asyncio.Event(), asyncio.Event()
    original = f.service.planner_compiler.compile
    async def blocked(request):
        entered.set()
        await release.wait()
        return await original(request)
    f.service.planner_compiler.compile = blocked
    first = asyncio.create_task(f.service.compile_plan(f.project_id, f.request, "concurrent"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        replay = await f.service.compile_plan(f.project_id, f.request, "concurrent")
        assert replay.status == "compiling"
    finally:
        release.set()
        await first
    assert len(f.calls) == 2


@pytest.mark.asyncio
async def test_suite_v2_preserves_master_outline_and_matches_reused_module_by_task_id():
    f = await fixture_v2()
    master = {
        "input": {"brief": "先展示整体，再展示结构"},
        "summary": "两图互补",
        "modules": [
            {"taskId": "overall", "moduleId": "suite-hero", "taskGoal": "整体识别"},
            {"taskId": "detail", "moduleId": "suite-hero", "taskGoal": "结构说明"},
        ],
    }
    async def snapshot(*_args):
        return master
    f.service.module_planning = SimpleNamespace(snapshot=snapshot)
    plan = await f.service.compile_plan(f.project_id, replace(f.request, module_plan_id=uuid4()), "master-v2")
    assert plan.snapshot["planningMaster"] == master
    for call, expected in zip(f.calls, master["modules"]):
        context = json.loads(call.user_prompt)
        assert context["planningMaster"] == master
        assert context["taskOutline"] == expected
