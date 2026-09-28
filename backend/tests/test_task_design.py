import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from backend.app.application.module_planning_v2 import build_v2_compiler_prompts, resolve_style_seed
from backend.app.schemas import BatchHeroModuleInput as HeroSchema, SuitePlanModuleCompileInput as SuiteSchema


@pytest.mark.parametrize('schema,module_id', [(HeroSchema, 'hero-freeform'), (SuiteSchema, 'suite-freeform')])
def test_manual_design_is_validated_and_retained_at_request_boundary(schema, module_id):
    design = {'productPresence': 'none', 'informationQuestion': '解释已确认参数'}
    value = schema(moduleId=module_id, resultCount=1, moduleParameters=[], taskDesign=design)
    assert value.model_dump()['taskDesign']['productPresence'] == 'none'
    with pytest.raises(ValidationError):
        schema(moduleId=module_id, resultCount=1, taskDesign={'productPresence': 'invented'})


def test_user_design_overrides_master_without_becoming_product_copy():
    from backend.tests.test_commerce_planning_flow import new_output
    outline = new_output('hero')['modules'][0]
    design = {'taskTitle': '手动标题', 'productPresence': 'context', 'informationQuestion': '怎样使用', 'visualMechanism': '手部操作'}
    _, user, snapshot = build_v2_compiler_prompts(
        seed=resolve_style_seed({'id': 'minimal'}), module={'id': 'hero-freeform', 'mode': 'hero'},
        module_parameters=[{'key': '主信息', 'value': '1000 Hz'}], custom_style='',
        task_outline=outline, task_design=design, market={}, output={}, constraints={},
    )
    context = json.loads(user)
    assert context['taskOutline']['productPresence'] == 'context'
    assert context['taskOutline']['informationQuestion'] == '怎样使用'
    assert context['explicitTaskDesign'] == design
    assert context['moduleParameters'] == [{'key': '主信息', 'value': '1000 Hz'}]
    assert snapshot['effectiveTaskOutline']['taskTitle'] == '手动标题'
    assert outline['productPresence'] == 'none'


def test_auto_presence_and_empty_fields_release_inherited_requirements():
    from backend.tests.test_commerce_planning_flow import new_output
    _, user, _ = build_v2_compiler_prompts(
        seed=resolve_style_seed({'id': 'minimal'}), module={'id': 'hero-freeform', 'mode': 'hero'},
        module_parameters=[], custom_style='', task_outline=new_output('hero')['modules'][0],
        task_design={'productPresence': 'auto', 'visualMechanism': ''}, market={}, output={}, constraints={},
    )
    context = json.loads(user)
    assert context['taskOutline']['productPresence'] == 'auto'
    assert context['taskOutline']['visualMechanism'] == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['hero', 'suite'])
async def test_manual_same_type_tasks_receive_independent_design_and_freeze_it(mode):
    from backend.tests.test_batch_generation_compile_service import _fixture as hero_fixture, _input
    from backend.tests.test_suite_planning_service import _fixture as suite_fixture
    from backend.app.application.batch_generation_service import BatchHeroModuleInput
    from backend.app.application.suite_planning_service import SuitePlanModuleInput, SuitePlanCompilationInput
    choices = [{'taskTitle': '只讲参数', 'productPresence': 'none'}, {'taskTitle': '展示使用', 'productPresence': 'context'}]
    if mode == 'hero':
        f = await hero_fixture()
        request = replace(_input(f.source_asset_id), modules=[BatchHeroModuleInput('hero-freeform', 1, task_id=f'task-{i}', task_design=d) for i,d in enumerate(choices)])
        batch = await f.service.compile_prompt_batch(f.project_id, request, 'manual-design')
        detail = await f.repository.get_batch_detail(batch.id, f.workspace_id)
        snapshots = [t.snapshot for t in detail.module_tasks]
        from backend.app.routes.batch_generations import _task_identity
        assert [_task_identity(t)['moduleLabel'] for t in detail.module_tasks] == [d['taskTitle'] for d in choices]
    else:
        f = await suite_fixture()
        request = SuitePlanCompilationInput(source_asset_ids=f.source_asset_ids, market_id='taobao', model_id='gpt-image-2-5', style_id='minimal', aspect_ratio='3:4', resolution='标准 1K', output_language='中文', modules=[SuitePlanModuleInput('suite-freeform', 1, task_id=f'task-{i}', task_design=d) for i,d in enumerate(choices)])
        plan = await f.service.compile_plan(f.project_id, request, 'manual-design')
        detail = await f.plans.get_plan_detail(plan.id, f.workspace_id, f.project_id)
        snapshots = [t.prompt_snapshot for t in detail.modules]
        assert [t.title for t in detail.modules] == [d['taskTitle'] for d in choices]
    contexts = [json.loads(c.user_prompt) for c in f.compiler.requests]
    assert [c['explicitTaskDesign'] for c in contexts] == choices
    assert [c['taskOutline']['productPresence'] for c in contexts] == ['none', 'context']
    assert all(c['moduleParameters'] == [] for c in contexts)
    assert len(contexts) == 2
    assert all(s['taskDesign'] == d for s,d in zip(snapshots,choices))
