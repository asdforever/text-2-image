from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.application.regular_design import regular_snapshot
from backend.app.application.suite_planning_service import SuitePlanCompilationInput, SuitePlanModuleInput
from backend.tests.test_suite_planning_service import _fixture


class Cards:
    market = SimpleNamespace(content='平台规则')
    style = SimpleNamespace(content='风格规则')

    def to_snapshot(self):
        return {'market': '平台规则', 'style': '风格规则'}


def make_snapshot(options=None):
    request = SimpleNamespace(market_id='taobao', custom_style='', aspect_ratio='3:4',
        resolution='标准 1K', output_language='中文', user_notes='', modules=[])
    selected = SimpleNamespace(task_id='detail', module_id='suite-detail',
        regular_task={'goal': '展示真实滚轮细节', 'copy': '滚轮细节'}, regular_options=options)
    return regular_snapshot(request, selected, None,
        {'id': 'suite-detail', 'label': '商品细节图', 'description': '展示真实细节'},
        [{'key': '材质', 'value': '塑料'}, {'key': '避免出现', 'value': '人物'}],
        {'label': '淘宝'}, {'id': 'minimal'}, Cards())


def test_absent_options_default_to_flexible_copy_and_preserve_other_rules():
    baseline = json.loads((Path(__file__).parent / 'fixtures/regular-conversation-default.json').read_text(encoding='utf-8'))
    result = make_snapshot()
    assert result['regularOptions']['copyPolicy'] == 'flexible'
    context = json.loads(result['compiledTaskPrompt'].split('\n', 1)[1])
    assert context['suggestedCopy'] == '滚轮细节'
    assert 'approvedCopy' not in context
    for key in baseline.keys() - {'compiledTaskPrompt'}:
        assert result[key] == baseline[key]


def test_visual_requirements_alone_do_not_lock_copy():
    result = make_snapshot({'visualRequirements': '左侧留白'})
    assert result['regularOptions']['copyPolicy'] == 'flexible'
    assert 'Render approvedCopy' not in result['compiledTaskPrompt']


def test_explicit_copy_lock_preserves_literal_copy():
    context = json.loads(make_snapshot({'copyPolicy': 'fixed'})['compiledTaskPrompt'].split('\n', 1)[1])
    assert context['approvedCopy'] == '滚轮细节'
    assert 'suggestedCopy' not in context


@pytest.mark.asyncio
async def test_latest_custom_parameters_override_stale_planning_assumptions():
    f = await _fixture()
    facts = [{'key': '退货政策', 'value': '7天免费退货'}, {'key': '排版要求', 'value': '保障信息作为主标题'}]
    request = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids,
        market_id='taobao', model_id='gpt-image-2-5', style_id='minimal', aspect_ratio='3:4',
        resolution='标准 1K', output_language='中文', creation_mode='regular',
        modules=[SuitePlanModuleInput('suite-detail', 1, facts,
            regular_task={'goal': '未提供服务承诺，仅展示材质', 'copy': '买得安心'})])
    plan = await f.service.compile_plan(f.project_id, request, 'latest-facts-priority')
    detail = await f.plans.get_plan_detail(plan.id, f.workspace_id, f.project_id)
    prompt = detail.modules[0].compiled_task_prompt
    context = json.loads(prompt.split('\n', 1)[1])
    assert context['assignedProductFacts'] == facts
    assert context['copyPolicy'] == 'flexible'
    assert 'currentInputPriority' in context
    assert 'currentInputPriority' in prompt.split('\n', 1)[0]
    assert 'Render approvedCopy' not in prompt
    assert not f.compiler.requests


def test_flexible_copy_replaces_original_copy_instruction_and_locks_supplied_facts():
    result = make_snapshot({'copyPolicy': 'flexible', 'visualRequirements': '左侧窗光'})
    prompt = result['compiledTaskPrompt']
    assert 'Render approvedCopy' not in prompt
    context = json.loads(prompt.split('\n', 1)[1])
    assert context['copyPolicy'] == 'flexible'
    assert context['visualRequirements'] == '左侧窗光'
    assert context['suggestedCopy'] == '滚轮细节'
    assert context['assignedProductFacts'] == [{'key': '材质', 'value': '塑料'}, {'key': '避免出现', 'value': '人物'}]
    assert context['lockedInformation']
    assert context['suiteConsistency'] == make_snapshot()['suiteConsistency']
    assert context['moduleDirection'] == make_snapshot()['moduleDirection']


@pytest.mark.asyncio
async def test_regular_options_reach_frozen_suite_prompt():
    f = await _fixture()
    request = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids,
        market_id='taobao', model_id='gpt-image-2-5', style_id='minimal', aspect_ratio='3:4',
        resolution='标准 1K', output_language='中文', creation_mode='regular',
        modules=[SuitePlanModuleInput('suite-detail', 1, [{'key': '自定义部位', 'value': '滚轮'}],
            regular_task={'goal': '展示细节', 'copy': '细节'},
            regular_options={'copyPolicy': 'fixed', 'visualRequirements': '不要文字遮挡滚轮'})])
    plan = await f.service.compile_plan(f.project_id, request, 'conversation-options')
    detail = await f.plans.get_plan_detail(plan.id, f.workspace_id, f.project_id)
    assert '不要文字遮挡滚轮' in detail.modules[0].compiled_task_prompt
    assert 'Render approvedCopy' in detail.modules[0].compiled_task_prompt
    assert not f.compiler.requests


@pytest.mark.asyncio
async def test_professional_request_cannot_use_regular_options():
    f = await _fixture()
    request = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids,
        market_id='taobao', model_id='gpt-image-2-5', style_id='minimal', aspect_ratio='3:4',
        resolution='标准 1K', output_language='中文',
        modules=[SuitePlanModuleInput('suite-detail', 1,
            regular_options={'copyPolicy': 'flexible'})])
    from backend.app.core.errors import AppError
    with pytest.raises(AppError) as error:
        await f.service.compile_plan(f.project_id, request, 'reject-professional-options')
    assert error.value.code == 'REGULAR_OPTIONS_MODE_MISMATCH'
    assert not f.compiler.requests
