from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest

from backend.app.application.batch_generation_confirmation_service import BatchGenerationConfirmationService
from backend.app.application.suite_planning_confirmation_service import SuitePlanningConfirmationService
from backend.app.batch_generation_repository import InMemoryBatchGenerationRepository
from backend.app.core.errors import AppError
from backend.app.application.batch_generation_worker import BatchGenerationWorker
from backend.app.application.project_asset_service import ProjectAssetService
from backend.tests.test_batch_generation_worker import SuccessEditor
from backend.tests.test_batch_generation_compile_service import _fixture as hero_fixture, _input, _add_project_asset
from backend.tests.test_suite_planning_v2 import fixture_v2
from backend.tests.test_hero_generation_confirm_service import _fixture as single_fixture, _compile_input, V2Compiler
from backend.tests.test_reverse_execution_batches import harness
from app.core.errors import AppError as ReverseAppError


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['regular', 'professional'])
@pytest.mark.parametrize('kind', ['hero', 'suite'])
async def test_manual_confirmation_is_frozen_for_this_batch_only(kind, mode):
    edited = '保留真实商品，主体向左，右侧留白。本次手动修改。'
    if kind == 'hero':
        f = await hero_fixture()
        request = _input(f.source_asset_id)
        request = replace(request, creation_mode=mode, modules=[replace(request.modules[0],
            regular_task={'goal': '展示商品', 'copy': '商品'} if mode == 'regular' else None)])
        first = await f.service.compile_prompt_batch(f.project_id, request, 'compile-first')
        detail = await f.repository.get_batch_detail(first.id, f.workspace_id)
        original = detail.module_tasks[0].compiled_task_prompt
        key = detail.module_tasks[0].module_key
        confirm = BatchGenerationConfirmationService(f.repository, f.service.identity_provider)
        await confirm.confirm_batch(f.project_id, first.id, {key: edited}, 'confirm-first')
        replay = await confirm.confirm_batch(f.project_id, first.id, {key: edited}, 'confirm-first')
        frozen = await f.repository.get_batch_detail(replay.id, f.workspace_id)
        with pytest.raises(AppError) as conflict:
            await confirm.confirm_batch(f.project_id, first.id, {key: '不同内容'}, 'confirm-first')
        assert conflict.value.code == 'IDEMPOTENCY_KEY_REUSED'
        second = await f.service.compile_prompt_batch(f.project_id, request, 'compile-second')
        fresh = await f.repository.get_batch_detail(second.id, f.workspace_id)
        assert fresh.module_tasks[0].compiled_task_prompt != edited
    else:
        f = await fixture_v2()
        valid_source_id = await _add_project_asset(f, 'source', uuid4())
        request = replace(f.request, source_asset_ids=[valid_source_id], creation_mode=mode, modules=[replace(f.request.modules[0],
            regular_task={'goal': '展示商品', 'copy': '商品'} if mode == 'regular' else None)])
        first = await f.service.compile_plan(f.project_id, request, 'compile-first')
        detail = await f.service.get_plan(f.project_id, first.id)
        original = detail.modules[0].compiled_task_prompt
        key = detail.modules[0].module_key
        batches = InMemoryBatchGenerationRepository()
        confirm = SuitePlanningConfirmationService(plan_repository=f.plans, batch_repository=batches,
            identity_provider=f.service.identity_provider)
        batch = await confirm.confirm_plan(f.project_id, first.id, expected_plan_revision=first.revision,
            module_task_prompts={key: edited}, idempotency_key='confirm-first')
        frozen = await batches.get_batch_detail(batch.id, f.workspace_id)
        second = await f.service.compile_plan(f.project_id, request, 'compile-second')
        fresh = await f.service.get_plan(f.project_id, second.id)
        assert fresh.modules[0].compiled_task_prompt == original
    task = frozen.module_tasks[0]
    assert task.compiled_task_prompt == original
    assert task.confirmed_task_prompt == task.final_prompt == edited
    assert task.final_prompt_sha256 == sha256(edited.encode()).hexdigest()
    editor = SuccessEditor()
    worker = BatchGenerationWorker(repository=f.repository if kind == 'hero' else batches,
        project_repository=f.projects, project_storage=f.storage,
        project_asset_service=ProjectAssetService(f.projects, f.storage, f.service.identity_provider),
        image_editor=editor, worker_id='manual-prompt-test', concurrency=1)
    completed_count = await worker.run_once(limit=1)
    result = await (f.repository if kind == 'hero' else batches).get_batch_detail(frozen.batch.id, f.workspace_id)
    assert completed_count == 1, [(slot.status, slot.error_code, slot.error_message) for slot in result.slots]
    assert editor.requests[0].prompt == edited


@pytest.mark.asyncio
async def test_single_hero_sends_manual_text_and_archives_it():
    f = await single_fixture(planner_version='v2', compiler=V2Compiler())
    task = await f.service.compile_prompt(f.project.id, _compile_input(f.source.id), 'compile')
    edited = task.compiled_task_prompt + ' 右侧增加留白。'
    completed = await f.service.confirm_generation(f.project.id, task.id, task_prompt=edited, idempotency_key='confirm')
    assert f.editor.requests[0].prompt == edited
    assert completed.final_prompt == completed.confirmed_task_prompt == edited
    assert completed.compiled_task_prompt == task.compiled_task_prompt


@pytest.mark.asyncio
async def test_reverse_override_is_used_once_archived_and_retained_on_batch_retry():
    project, plan, plans, generation, editor, _ = await harness()
    task_id = plan.document['tasks'][0]['id']
    edited = '本次手动描述，商品向左，右侧留白。'
    generated = await generation.generate(project, plan.revision, plan_id=plan.id, task_ids=[task_id],
        prompt_overrides={task_id: edited})
    assert editor.requests[0].prompt == edited
    batch = (await generation.list_batches(project, plan.id))[0]
    assert batch.document['tasks'][0]['promptDraft'] == edited
    assert batch.document['tasks'][0]['compiledPrompt'] != edited
    stored = await plans.get(project, plan.id)
    assert all(not task.get('promptDraft') for task in stored.document['tasks'])
    assert all('compiledPrompt' not in task for task in stored.document['tasks'])
    retried = await generation.generate(project, generated.revision, plan_id=plan.id, batch_id=batch.id, task_ids=[task_id])
    assert editor.requests[-1].prompt == edited
    await generation.generate(project, retried.revision, plan_id=plan.id, task_ids=[task_id])
    assert editor.requests[-1].prompt != edited


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [{'missing': '文本'}, {'TASK': ''}, {'TASK': ' '}, {'TASK': 'x' * 50001}, []])
async def test_reverse_invalid_override_does_not_call_image_provider(overrides):
    project, plan, _, generation, editor, _ = await harness()
    task_id = plan.document['tasks'][0]['id']
    if isinstance(overrides, dict) and 'TASK' in overrides:
        overrides = {task_id: overrides['TASK']}
    with pytest.raises(ReverseAppError) as error:
        await generation.generate(project, plan.revision, plan_id=plan.id, task_ids=[task_id], prompt_overrides=overrides)
    assert error.value.code == 'REVERSE_PROMPT_OVERRIDES_INVALID'
    assert editor.requests == []


@pytest.mark.asyncio
async def test_reverse_retry_cannot_replace_frozen_prompt():
    project, plan, _, generation, editor, _ = await harness()
    task_id = plan.document['tasks'][0]['id']
    generated = await generation.generate(project, plan.revision, plan_id=plan.id, task_ids=[task_id])
    batch = (await generation.list_batches(project, plan.id))[0]
    with pytest.raises(ReverseAppError) as error:
        await generation.generate(project, generated.revision, plan_id=plan.id, batch_id=batch.id,
            task_ids=[task_id], prompt_overrides={task_id: '替换'})
    assert error.value.code == 'REVERSE_BATCH_PROMPT_IMMUTABLE'
    assert len(editor.requests) == 1
