from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from backend.app.application.suite_planning_service import SuitePlanCompilationInput, SuitePlanModuleInput
from backend.app.core.errors import AppError
from backend.tests.test_planning_conversation_service import setup


async def applied_fixture():
    f, service, snapshot, session = await setup()
    f.master_service.conversations = service
    f.service.module_planning = f.master_service
    f.master.result = {'kind': 'revision', 'message': '改标题', 'operations': [
        {'kind': 'set_module', 'taskId': 'suite-hero', 'changes': {'taskTitle': '新的首屏'}}]}
    body = dict(expectedRevision=session['revision'], text='仅改首屏标题',
        input=f.input.model_dump(mode='json'), snapshot=snapshot)
    turn = await service.submit_turn(f.project_id, UUID(session['id']), body, 'edit')
    await service.run_turn(service.scope(f.project_id, 'suite', 'professional'),
        UUID(session['id']), UUID(turn['turn']['id']))
    current = await service.get(f.project_id, 'suite', 'professional')
    applied = await service.apply(f.project_id, UUID(session['id']), dict(
        expectedRevision=current['revision'], candidatePlanId=current['previewPlanId'],
        input=body['input'], snapshot=snapshot))
    return f, applied


@pytest.mark.asyncio
async def test_applied_version_and_new_manual_parameters_are_frozen_in_new_generation():
    f, applied = await applied_fixture()
    request = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids,
        market_id='taobao', model_id='gpt-image-2-5', style_id='minimal', aspect_ratio='3:4',
        resolution='标准 1K', output_language='中文', module_plan_id=UUID(applied['currentPlanId']),
        planning_applied_version_id=UUID(applied['currentVersionId']),
        modules=[SuitePlanModuleInput('suite-hero', 1, [{'key': '用户自定义新参数', 'value': '不要人物'}])])
    first = await f.service.compile_plan(f.project_id, request, 'new-version-compile')
    original = await f.plans.get_plan_detail(first.id, f.workspace_id, f.project_id)
    assert original.plan.snapshot['planningAppliedVersionId'] == applied['currentVersionId']
    assert '用户自定义新参数' in f.compiler.requests[-1].user_prompt
    changed = replace(request, modules=[SuitePlanModuleInput('suite-hero', 1,
        [{'key': '用户自定义新参数', 'value': '不要文字'}])])
    with pytest.raises(AppError) as error:
        await f.service.compile_plan(f.project_id, changed, 'new-version-compile')
    assert error.value.code == 'IDEMPOTENCY_KEY_REUSED'
    await f.service.compile_plan(f.project_id, changed, 'new-version-compile-2')
    recovered = await f.plans.get_plan_detail(first.id, f.workspace_id, f.project_id)
    assert recovered.plan.snapshot == original.plan.snapshot
    assert recovered.modules[0].prompt_snapshot == original.modules[0].prompt_snapshot


@pytest.mark.asyncio
async def test_compile_rejects_version_not_belonging_to_applied_plan():
    f, applied = await applied_fixture()
    request = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids,
        market_id='taobao', model_id='gpt-image-2-5', style_id='minimal', aspect_ratio='3:4',
        resolution='标准 1K', output_language='中文', module_plan_id=UUID(applied['currentPlanId']),
        planning_applied_version_id=uuid4(), modules=[SuitePlanModuleInput('suite-hero', 1)])
    with pytest.raises(AppError) as error:
        await f.service.compile_plan(f.project_id, request, 'bad-version')
    assert error.value.code == 'MODULE_PLAN_NOT_APPLIED'
    assert not f.compiler.requests
