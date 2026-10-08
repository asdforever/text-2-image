from copy import deepcopy
from uuid import UUID
import pytest
from backend.tests.test_module_planning import fixture
from backend.app.application.planning_conversation_service import PlanningConversationService
from backend.app.planning_conversation_repository import MemoryPlanningConversationRepository

async def setup():
    f = await fixture()
    p = await f.master_service.plan(f.project_id, f.input, 'initial')
    s = PlanningConversationService(MemoryPlanningConversationRepository(), f.master_service)
    snap = dict(plan=p, parameterOverrides={}, regularOptions={})
    session = await s.bootstrap(f.project_id, dict(mode='suite', creationMode='professional', input=f.input.model_dump(mode='json'), snapshot=snap))
    return f,s,snap,session

@pytest.mark.asyncio
async def test_clarification_replay_and_frozen_rules():
    f,s,snap,session = await setup()
    f.master.result = dict(kind='clarification', message='改文案还是场景？', operations=[])
    payload = dict(expectedRevision=session['revision'], text='不满意', input=f.input.model_dump(mode='json'), snapshot=snap)
    submitted = await s.submit_turn(f.project_id, UUID(session['id']), payload, 'feedback')
    replay = await s.submit_turn(f.project_id, UUID(session['id']), payload, 'feedback')
    assert replay['turn']['id'] == submitted['turn']['id']
    scope = s.scope(f.project_id, 'suite', 'professional')
    await s.run_turn(scope, UUID(session['id']), UUID(submitted['turn']['id']))
    current = await s.get(f.project_id, 'suite', 'professional')
    assert current['currentPlanId'] == snap['plan']['id']
    assert current['previewPlanId'] is None
    assert current['currentTurn']['status'] == 'clarification'
    assert len(f.master.calls) == 2
    assert f.master.calls[0].system_prompt in f.master.calls[1].system_prompt

@pytest.mark.asyncio
async def test_preview_apply_and_candidate_guard():
    f,s,snap,session = await setup()
    f.master.result = dict(kind='revision', message='已改标题', operations=[dict(kind='set_module', taskId='suite-hero', changes=dict(taskTitle='新标题'))])
    submitted = await s.submit_turn(f.project_id, UUID(session['id']), dict(expectedRevision=session['revision'], text='修改标题', input=f.input.model_dump(mode='json'), snapshot=snap), 'one')
    await s.run_turn(s.scope(f.project_id,'suite','professional'), UUID(session['id']), UUID(submitted['turn']['id']))
    current = await s.get(f.project_id,'suite','professional')
    assert current['previewSnapshot']['plan']['modules'][0]['taskTitle'] == '新标题'
    assert (await f.master_service.latest(f.project_id,'suite'))['id'] == snap['plan']['id']
    applied = await s.apply(f.project_id, UUID(session['id']),dict(expectedRevision=current['revision'], candidatePlanId=current['previewPlanId'],input=f.input.model_dump(mode='json'),snapshot=snap))
    assert applied['currentVersionId']
    assert applied['currentSnapshot']['plan']['modules'][0]['taskTitle'] == '新标题'
from datetime import datetime, timezone, timedelta
from backend.app.core.errors import AppError

@pytest.mark.asyncio
async def test_failure_retains_preview_and_retry_new_key():
    f,s,snap,session=await setup()
    f.master.result=dict(kind='revision',message='调整',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(taskTitle='预览'))])
    body=dict(expectedRevision=session['revision'],text='改标题',input=f.input.model_dump(mode='json'),snapshot=snap)
    first=await s.submit_turn(f.project_id,UUID(session['id']),body,'a')
    scope=s.scope(f.project_id,'suite','professional');sid=UUID(session['id'])
    await s.run_turn(scope,sid,UUID(first['turn']['id']))
    current=await s.get(f.project_id,'suite','professional');pending=current['previewPlanId']
    f.master.result=dict(kind='revision',message='无效',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(moduleId='invented'))])
    body['expectedRevision']=current['revision'];body['text']='继续'
    second=await s.submit_turn(f.project_id,sid,body,'b');await s.run_turn(scope,sid,UUID(second['turn']['id']))
    current=await s.get(f.project_id,'suite','professional')
    assert current['previewPlanId']==pending
    assert current['currentTurn']['status']=='failed'
    replay=await s.submit_turn(f.project_id,sid,body,'b')
    assert replay['owner'] is False
    with pytest.raises(AppError):
        await s.submit_turn(f.project_id,sid,{**body,'text':'另外内容'},'b')

@pytest.mark.asyncio
async def test_running_manual_change_is_stale_and_restart_timeout_persists():
    f,s,snap,session=await setup();sid=UUID(session['id']);scope=s.scope(f.project_id,'suite','professional')
    f.master.result=dict(kind='revision',message='改',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(taskTitle='预览'))])
    body=dict(expectedRevision=session['revision'],text='改标题',input=f.input.model_dump(mode='json'),snapshot=snap)
    submitted=await s.submit_turn(f.project_id,sid,body,'a')
    manual=deepcopy(snap);manual['plan']['modules'][1]['taskTitle']='手动'
    await s.sync(f.project_id,sid,dict(expectedRevision=submitted['session']['revision'],input=body['input'],snapshot=manual))
    await s.run_turn(scope,sid,UUID(submitted['turn']['id']))
    current=await s.get(f.project_id,'suite','professional')
    assert current['currentTurn']['status']=='stale'
    assert current['previewPlanId'] is None
    second=await s.submit_turn(f.project_id,sid,{**body,'snapshot':manual,'expectedRevision':current['revision']},'b')
    s.repository.turns[UUID(second['turn']['id'])]['createdAt']=(datetime.now(timezone.utc)-timedelta(seconds=541)).isoformat()
    restarted=PlanningConversationService(s.repository,f.master_service)
    current=await restarted.get(f.project_id,'suite','professional')
    expired=await restarted.turn(f.project_id,sid,UUID(second['turn']['id']))
    assert expired['status']=='failed'
    assert current['activeTurnId'] is None
    assert len(f.master.calls)==2

@pytest.mark.asyncio
async def test_apply_merges_manual_field_and_restore_preserves_history():
    f,s,snap,session=await setup();sid=UUID(session['id']);scope=s.scope(f.project_id,'suite','professional')
    f.master.result=dict(kind='revision',message='改',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(taskTitle='预览'))])
    submitted=await s.submit_turn(f.project_id,sid,dict(expectedRevision=session['revision'],text='改标题',input=f.input.model_dump(mode='json'),snapshot=snap),'a')
    await s.run_turn(scope,sid,UUID(submitted['turn']['id']))
    current=await s.get(f.project_id,'suite','professional')
    manual=deepcopy(snap);manual['plan']['modules'][1]['taskTitle']='手动'
    applied=await s.apply(f.project_id,sid,dict(expectedRevision=current['revision'],candidatePlanId=current['previewPlanId'],input=f.input.model_dump(mode='json'),snapshot=manual))
    assert applied['currentSnapshot']['plan']['modules'][1]['taskTitle']=='手动'
    restored=await s.restore(f.project_id,sid,dict(expectedRevision=applied['revision'],versionId=applied['currentVersionId'],input=f.input.model_dump(mode='json'),snapshot=applied['currentSnapshot']))
    assert restored['currentVersionId']!=applied['currentVersionId']
    assert len((await s.versions(f.project_id,sid))['items'])==2

@pytest.mark.asyncio
async def test_scope_bootstrap_and_generation_guard():
    f,s,snap,session=await setup()
    f.master_service.conversations=s
    assert await s.get(f.project_id,'hero','regular') is None
    with pytest.raises(AppError):await s.get(__import__('uuid').uuid4(),'suite','professional')
    bad=deepcopy(snap);bad['plan']['id']=str(__import__('uuid').uuid4())
    with pytest.raises(AppError):await s.bootstrap(f.project_id,dict(mode='hero',creationMode='professional',input={**f.input.model_dump(mode='json'),'mode':'hero'},snapshot=bad))
    f.master.result=dict(kind='revision',message='改',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(taskTitle='预览'))])
    submitted=await s.submit_turn(f.project_id,UUID(session['id']),dict(expectedRevision=session['revision'],text='改标题',input=f.input.model_dump(mode='json'),snapshot=snap),'a')
    await s.run_turn(s.scope(f.project_id,'suite','professional'),UUID(session['id']),UUID(submitted['turn']['id']))
    current=await s.get(f.project_id,'suite','professional')
    with pytest.raises(AppError) as e:await f.master_service.snapshot(f.project_id,UUID(current['previewPlanId']),'suite')
    assert e.value.code=='MODULE_PLAN_NOT_APPLIED'
@pytest.mark.asyncio
async def test_regular_custom_options_addition_and_request_retains_manual_snapshot():
    f=await fixture();f.input=f.input.model_copy(update={'creationMode':'regular'})
    f.master.result=dict(summary='内容',warnings=[],modules=[dict(taskId='one',moduleId='suite-hero',taskTitle='标题',reason='理由',suggestedCopy='批准文案',moduleParameters=[])])
    p=await f.master_service.plan(f.project_id,f.input,'initial')
    s=PlanningConversationService(MemoryPlanningConversationRepository(),f.master_service)
    snap=dict(plan=p,parameterOverrides={'one':[{'key':'自定义','value':'保留'}]},regularOptions={},generationSettings={'outputLanguage':'中文'})
    session=await s.bootstrap(f.project_id,dict(mode='suite',creationMode='regular',input=f.input.model_dump(mode='json'),snapshot=snap))
    f.master.result=dict(kind='revision',message='新增',operations=[dict(kind='add_module',module=dict(moduleId='suite-detail',taskTitle='细节',reason='可见',suggestedCopy='',moduleParameters=[])),dict(kind='set_module',taskId='one',changes=dict(taskTitle='新标题'))])
    result=await s.submit_turn(f.project_id,UUID(session['id']),dict(expectedRevision=session['revision'],text='新增细节',input=f.input.model_dump(mode='json'),snapshot=snap),'a')
    await s.run_turn(s.scope(f.project_id,'suite','regular'),UUID(session['id']),UUID(result['turn']['id']))
    current=await s.get(f.project_id,'suite','regular')
    assert len(current['previewSnapshot']['plan']['modules'])==2
    assert current['previewSnapshot']['plan']['modules'][0]['suggestedCopy']=='批准文案'
    assert current['previewSnapshot']['parameterOverrides']==snap['parameterOverrides']
    import json
    context=json.loads(f.master.calls[-1].user_prompt)
    assert context['currentEffectiveSnapshot']['generationSettings']==snap['generationSettings']
    assert context['currentEffectiveSnapshot']['parameterOverrides']==snap['parameterOverrides']

@pytest.mark.asyncio
async def test_full_length_manual_regular_goal_survives_conversation_and_apply():
    f=await fixture();f.input=f.input.model_copy(update={'creationMode':'regular'})
    f.master.result=dict(summary='内容',warnings=[],modules=[dict(taskId='one',moduleId='suite-hero',taskTitle='标题',reason='简短自动目标',suggestedCopy='批准文案',moduleParameters=[])])
    p=await f.master_service.plan(f.project_id,f.input,'initial')
    s=PlanningConversationService(MemoryPlanningConversationRepository(),f.master_service)
    snap=dict(plan=p,parameterOverrides={},regularOptions={})
    snap['plan']['modules'][0]['reason']='真实商品信息'*333+'补充'
    assert len(snap['plan']['modules'][0]['reason'])==2000
    session=await s.bootstrap(f.project_id,dict(mode='suite',creationMode='regular',input=f.input.model_dump(mode='json'),snapshot=snap))
    f.master.result=dict(kind='revision',message='仅改标题',operations=[dict(kind='set_module',taskId='one',changes=dict(taskTitle='新标题'))])
    turn=await s.submit_turn(f.project_id,UUID(session['id']),dict(expectedRevision=session['revision'],text='仅改标题',input=f.input.model_dump(mode='json'),snapshot=snap),'long-goal')
    await s.run_turn(s.scope(f.project_id,'suite','regular'),UUID(session['id']),UUID(turn['turn']['id']))
    current=await s.get(f.project_id,'suite','regular')
    applied=await s.apply(f.project_id,UUID(session['id']),dict(expectedRevision=current['revision'],candidatePlanId=current['previewPlanId'],input=f.input.model_dump(mode='json'),snapshot=snap))
    assert applied['currentSnapshot']['plan']['modules'][0]['reason']==snap['plan']['modules'][0]['reason']
    f.master_service.conversations=s
    assert (await f.master_service.snapshot(f.project_id,UUID(applied['currentPlanId']),'suite'))['modules'][0]['reason']==snap['plan']['modules'][0]['reason']
    snap['plan']['modules'][0]['reason']+='超'
    with pytest.raises(AppError) as error:
        await s.sync(f.project_id,UUID(session['id']),dict(expectedRevision=applied['revision'],input=f.input.model_dump(mode='json'),snapshot=snap))
    assert error.value.code=='CONVERSATION_SNAPSHOT_INVALID'

@pytest.mark.asyncio
async def test_applied_version_validation_matches_new_merged_plan():
    f,s,snap,session=await setup();sid=UUID(session['id'])
    f.master.result=dict(kind='revision',message='调整',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(taskTitle='预览'))])
    turn=await s.submit_turn(f.project_id,sid,dict(expectedRevision=session['revision'],text='修改',input=f.input.model_dump(mode='json'),snapshot=snap),'a')
    await s.run_turn(s.scope(f.project_id,'suite','professional'),sid,UUID(turn['turn']['id']))
    current=await s.get(f.project_id,'suite','professional');manual=deepcopy(snap);manual['plan']['modules'][1]['taskTitle']='手动'
    applied=await s.apply(f.project_id,sid,dict(expectedRevision=current['revision'],candidatePlanId=current['previewPlanId'],input=f.input.model_dump(mode='json'),snapshot=manual))
    version=await s.validate_applied_version(f.project_id,UUID(applied['currentPlanId']),UUID(applied['currentVersionId']),'suite')
    assert version['planId']==applied['currentPlanId']
    assert (await f.master_service.get(f.project_id,UUID(applied['currentPlanId'])))['modules'][1]['taskTitle']=='手动'
    with pytest.raises(AppError):await s.validate_applied_version(f.project_id,UUID(current['previewPlanId']),UUID(applied['currentVersionId']),'suite')
@pytest.mark.asyncio
async def test_bootstrap_null_requires_explicit_plan_without_external_call():
    f=await fixture();s=PlanningConversationService(MemoryPlanningConversationRepository(),f.master_service)
    with pytest.raises(AppError) as e:
        await s.bootstrap(f.project_id,dict(mode='suite',creationMode='professional',input=f.input.model_dump(mode='json'),snapshot=None))
    assert e.value.code=='INITIAL_PLAN_REQUIRED'
    assert len(f.master.calls)==0

@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['revision','clarification'])
async def test_context_change_during_model_call_marks_result_stale(kind):
    f,s,snap,session=await setup();sid=UUID(session['id']);scope=s.scope(f.project_id,'suite','professional')
    turn=await s.submit_turn(f.project_id,sid,dict(expectedRevision=session['revision'],text='change',input=f.input.model_dump(mode='json'),snapshot=snap),'change')
    original=f.config.get_published
    async def changed():
        from dataclasses import replace
        published=await original()
        return replace(published,version_no=published.version_no+1)
    async def model(request):
        f.config.get_published=changed
        return dict(kind=kind,message='change',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(taskTitle='preview'))] if kind=='revision' else [])
    f.master.plan_modules=model
    await s.run_turn(scope,sid,UUID(turn['turn']['id']))
    current=await s.get(f.project_id,'suite','professional')
    assert current['currentTurn']['status']=='stale'
    assert current['previewPlanId'] is None

@pytest.mark.asyncio
async def test_professional_auto_sidecar_survives_round_and_system_reply_contract():
    f,s,snap,session=await setup();sid=UUID(session['id'])
    snap['taskDesignOverrides']={'suite-hero':{'productPresence':'auto'}}
    f.master.result=dict(kind='revision',message='title',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(taskTitle='title'))])
    turn=await s.submit_turn(f.project_id,sid,dict(expectedRevision=session['revision'],text='title',input=f.input.model_dump(mode='json'),snapshot=snap),'auto')
    await s.run_turn(s.scope(f.project_id,'suite','professional'),sid,UUID(turn['turn']['id']))
    current=await s.get(f.project_id,'suite','professional')
    assert current['previewSnapshot']['taskDesignOverrides']==snap['taskDesignOverrides']
    assert current['previewSnapshot']['plan']['modules'][0]['productPresence']=='full'
    assert 'conversationReply' in f.master.calls[-1].system_prompt
    assert f.master.calls[0].system_prompt in f.master.calls[-1].system_prompt

@pytest.mark.asyncio
async def test_invalid_snapshot_schema_is_controlled_in_service():
    f,s,snap,session=await setup();snap['plan']['modules']=[]
    with pytest.raises(AppError) as e:
        await s.sync(f.project_id,UUID(session['id']),dict(expectedRevision=session['revision'],input=f.input.model_dump(mode='json'),snapshot=snap))
    assert e.value.code=='CONVERSATION_SNAPSHOT_INVALID'

@pytest.mark.asyncio
async def test_skill_change_after_preview_blocks_apply():
    f,s,snap,session=await setup();sid=UUID(session['id'])
    f.master.result=dict(kind='revision',message='title',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(taskTitle='preview'))])
    turn=await s.submit_turn(f.project_id,sid,dict(expectedRevision=session['revision'],text='title',input=f.input.model_dump(mode='json'),snapshot=snap),'skill')
    await s.run_turn(s.scope(f.project_id,'suite','professional'),sid,UUID(turn['turn']['id']))
    current=await s.get(f.project_id,'suite','professional')
    original_prepare=s.planner.prepare
    async def changed_skill(*args,**kwargs):
        planner,request,frozen,catalog=await original_prepare(*args,**kwargs)
        frozen['skill']={'contentHash':'new rule content'}
        return planner,request,frozen,catalog
    s.planner.prepare=changed_skill
    with pytest.raises(AppError) as error:
        await s.apply(f.project_id,sid,dict(expectedRevision=current['revision'],candidatePlanId=current['previewPlanId'],input=f.input.model_dump(mode='json'),snapshot=snap))
    assert error.value.code=='PLANNING_CONTEXT_CHANGED'
    assert (await s.get(f.project_id,'suite','professional'))['currentPlanId']==snap['plan']['id']
@pytest.mark.asyncio
@pytest.mark.parametrize('drift',['materials','provider'])
async def test_material_or_provider_drift_during_model_retains_existing_preview(drift):
    from dataclasses import replace
    from types import SimpleNamespace
    f,s,snap,session=await setup();sid=UUID(session['id']);scope=s.scope(f.project_id,'suite','professional')
    f.master.result=dict(kind='revision',message='first',operations=[dict(kind='set_module',taskId='suite-hero',changes=dict(taskTitle='preview'))])
    body=dict(expectedRevision=session['revision'],text='first',input=f.input.model_dump(mode='json'),snapshot=snap)
    turn=await s.submit_turn(f.project_id,sid,body,'first');await s.run_turn(scope,sid,UUID(turn['turn']['id']))
    current=await s.get(f.project_id,'suite','professional');old=current['previewPlanId']
    if drift=='provider':
        class Resolver:
            snapshot={'model':'first'}
            async def bind(self,config,planner):return SimpleNamespace(compiler=planner,snapshot=self.snapshot)
        resolver=Resolver();f.master_service.prompt_models=resolver
    body.update(expectedRevision=current['revision'],text='second')
    second=await s.submit_turn(f.project_id,sid,body,'second')
    original_get=f.projects.get_object
    async def changed_object(*args):
        obj=await original_get(*args)
        return replace(obj,sha256='changed-hash')
    async def model(request):
        if drift=='materials':f.projects.get_object=changed_object
        else:resolver.snapshot={'model':'second'}
        return dict(kind='clarification',message='question',operations=[])
    f.master.plan_modules=model
    await s.run_turn(scope,sid,UUID(second['turn']['id']))
    current=await s.get(f.project_id,'suite','professional')
    assert current['currentTurn']['status']=='stale'
    assert current['previewPlanId']==old


@pytest.mark.asyncio
async def test_answer_discusses_plan_without_creating_candidate_or_changing_snapshot(monkeypatch):
    from backend.app.application.planning_conversation_models import Reply
    f, service, snapshot, session = await setup()
    question = '这里面应该有不展示商品整体，只展示糖的那种吧'
    f.master.result = dict(kind='answer', message='可以采用仅展示糖粒的画面；目前方案里还没有单独安排这一张。需要修改时可以告诉我。', operations=[])
    async def no_candidate(*args, **kwargs):
        raise AssertionError('A discussion must not create a candidate')
    monkeypatch.setattr(service, '_candidate', no_candidate)
    submitted = await service.submit_turn(f.project_id, UUID(session['id']), dict(expectedRevision=session['revision'], text=question, input=f.input.model_dump(mode='json'), snapshot=snapshot), 'ask')
    await service.run_turn(service.scope(f.project_id, 'suite', 'professional'), UUID(session['id']), UUID(submitted['turn']['id']))
    current = await service.get(f.project_id, 'suite', 'professional')
    assert current['currentTurn']['status'] == 'completed'
    assert current['currentTurn']['result']['kind'] == 'answer'
    assert current['currentSnapshot'] == session['currentSnapshot']
    assert current['appliedSnapshot'] == session['appliedSnapshot']
    assert current['previewPlanId'] is None
    assert current['currentVersionId'] is None
    assert current['messages'][-1]['text'] == f.master.result['message']
    assert len(f.master.calls) == 2
    assert f.master.calls[0].system_prompt in f.master.calls[1].system_prompt
    context = __import__('json').loads(f.master.calls[1].user_prompt)
    assert '提问、解释、比较、建议和讨论返回 answer' in context['conversationInstructions']
    assert question in context['conversationInstructions']
    with pytest.raises(__import__('pydantic').ValidationError):
        Reply.model_validate(dict(kind='answer', message='解释', operations=[dict(kind='delete_module', taskId='suite-hero')]))


@pytest.mark.asyncio
async def test_discussion_preserves_existing_preview_then_explicit_revision_still_works():
    f, service, snapshot, session = await setup()
    sid = UUID(session['id']); scope = service.scope(f.project_id, 'suite', 'professional')
    body = dict(expectedRevision=session['revision'], text='把第一张标题改成新品', input=f.input.model_dump(mode='json'), snapshot=snapshot)
    f.master.result = dict(kind='revision', message='已调整标题', operations=[dict(kind='set_module', taskId='suite-hero', changes=dict(taskTitle='新品'))])
    first = await service.submit_turn(f.project_id, sid, body, 'edit-1')
    await service.run_turn(scope, sid, UUID(first['turn']['id']))
    pending = await service.get(f.project_id, 'suite', 'professional')
    f.master.result = dict(kind='answer', message='第一张负责建立商品识别，因此建议保留完整商品。', operations=[])
    second = await service.submit_turn(f.project_id, sid, {**body, 'expectedRevision': pending['revision'], 'text': '为什么第一张需要展示整体？'}, 'ask-preview')
    await service.run_turn(scope, sid, UUID(second['turn']['id']))
    answered = await service.get(f.project_id, 'suite', 'professional')
    assert answered['currentTurn']['status'] == 'completed'
    assert answered['previewPlanId'] == pending['previewPlanId']
    assert answered['previewSnapshot'] == pending['previewSnapshot']
    assert answered['currentSnapshot'] == pending['currentSnapshot']
    f.master.result = dict(kind='revision', message='第二张改成局部特写', operations=[dict(kind='set_module', taskId='suite-detail', changes=dict(taskTitle='局部特写'))])
    third = await service.submit_turn(f.project_id, sid, {**body, 'expectedRevision': answered['revision'], 'text': '按这个建议，把第二张改成局部特写'}, 'edit-2')
    await service.run_turn(scope, sid, UUID(third['turn']['id']))
    updated = await service.get(f.project_id, 'suite', 'professional')
    assert updated['currentTurn']['status'] == 'preview'
    assert updated['previewSnapshot']['plan']['modules'][0]['taskTitle'] == '新品'
    assert updated['previewSnapshot']['plan']['modules'][1]['taskTitle'] == '局部特写'
    assert updated['currentPlanId'] == session['currentPlanId']


@pytest.mark.asyncio
async def test_submission_reads_materials_once_and_still_validates_latest_snapshot(monkeypatch):
    f, service, snapshot, session = await setup()
    reads = []
    original_get = f.storage.get
    async def counted_get(key):
        reads.append(key)
        return await original_get(key)
    monkeypatch.setattr(f.storage, 'get', counted_get)
    submitted = await service.submit_turn(f.project_id, UUID(session['id']), dict(expectedRevision=session['revision'], text='为什么这样规划？', input=f.input.model_dump(mode='json'), snapshot=snapshot), 'fast-send')
    assert submitted['turn']['status'] == 'generating'
    assert len(reads) == len(f.input.sourceAssetIds) + len(f.input.referenceAssetIds)
    assert submitted['turn']['document']['frozen']['sourceAssets']
