from uuid import UUID, uuid4
import asyncio
import pytest
from backend.app.application.planning_conversation_models import ConversationScope
from backend.app.planning_conversation_repository import MemoryPlanningConversationRepository
from backend.app.core.errors import AppError

@pytest.mark.asyncio
async def test_scope_replay_cas_and_token():
    repo = MemoryPlanningConversationRepository()
    scope = ConversationScope(uuid4(), uuid4(), 'suite', 'regular')
    session = await repo.ensure_session(scope, {'currentSnapshot': {'title': 'original'}})
    sid = UUID(session['id'])
    assert (await repo.ensure_session(scope, {}))['id'] == session['id']
    for other in [ConversationScope(uuid4(),scope.project_id,'suite','regular'), ConversationScope(scope.workspace_id,uuid4(),'suite','regular'), ConversationScope(scope.workspace_id,scope.project_id,'hero','regular'), ConversationScope(scope.workspace_id,scope.project_id,'suite','professional')]:
        assert await repo.get_session(other, sid) is None
    first, replay = await asyncio.gather(*[repo.reserve_turn(scope,sid,'one','a'*64,1,{'text':'edit'}) for _ in range(2)])
    assert first[2] and not replay[2]
    assert first[1]['id'] == replay[1]['id']
    with pytest.raises(AppError) as error:
        await repo.reserve_turn(scope,sid,'one','b'*64,1,{})
    assert error.value.code == 'IDEMPOTENCY_KEY_REUSED'
    with pytest.raises(AppError) as error:
        await repo.reserve_turn(scope,sid,'two','b'*64,first[0]['revision'],{})
    assert error.value.code == 'CONVERSATION_BUSY'
    tid = UUID(first[1]['id'])
    with pytest.raises(AppError) as error:
        await repo.finish_turn(scope,sid,tid,uuid4(),{})
    assert error.value.code == 'TURN_TOKEN_MISMATCH'
    completed = await repo.finish_turn(scope,sid,tid,UUID(first[1]['executionToken']),{'status':'completed','previewSnapshot':{'title':'preview'},'previewPlanId':str(uuid4())})
    assert completed['currentSnapshot'] == {'title':'original'}
    assert completed['previewSnapshot'] == {'title':'preview'}
    assert await repo.finish_turn(scope,sid,tid,UUID(first[1]['executionToken']),{'status':'failed'}) == completed
    with pytest.raises(AppError) as error:
        await repo.sync_snapshot(scope,sid,1,{})
    assert error.value.code == 'REVISION_CONFLICT'

@pytest.mark.asyncio
async def test_versions_snapshot_immutability_discard_and_pagination():
    repo = MemoryPlanningConversationRepository()
    scope = ConversationScope(uuid4(),uuid4(),'hero','professional')
    state = await repo.ensure_session(scope,{})
    sid = UUID(state['id'])
    snapshot = {'tasks':[{'taskId':'stable','title':'one'}]}
    state = await repo.apply_version(scope,sid,state['revision'],uuid4(),snapshot)
    v1 = state['currentVersionId']
    snapshot['tasks'][0]['title'] = 'mutated'
    state = await repo.sync_snapshot(scope,sid,state['revision'],{'title':'manual'})
    state = await repo.discard_preview(scope,sid,state['revision'])
    assert state['currentSnapshot'] == {'title':'manual'}
    state = await repo.apply_version(scope,sid,state['revision'],uuid4(),{'title':'two'},UUID(v1))
    page = await repo.list_versions(scope,sid,None,1)
    assert page['items'][0]['versionNumber'] == 2
    assert page['items'][0]['restoredFromVersionId'] == v1
    previous = await repo.list_versions(scope,sid,UUID(page['nextCursor']),1)
    assert previous['items'][0]['snapshot']['tasks'][0]['title'] == 'one'
    assert previous['nextCursor'] is None
    assert (await repo.list_turns(scope,sid,None,10))['items'] == []


@pytest.mark.asyncio
async def test_scoped_lookup_does_not_create_and_failed_turn_preserves_preview():
    repo = MemoryPlanningConversationRepository()
    scope = ConversationScope(uuid4(),uuid4(),'suite','professional')
    assert await repo.find_session(scope) is None
    state = await repo.ensure_session(scope,{'previewSnapshot':{'title':'previous'},'previewPlanId':str(uuid4()),'appliedSnapshot':{'title':'baseline'}})
    sid = UUID(state['id'])
    assert (await repo.find_session(scope))['id'] == state['id']
    state, turn, _ = await repo.reserve_turn(scope,sid,'one','a'*64,1,{})
    tid = UUID(turn['id'])
    assert (await repo.get_turn(scope,sid,tid))['status'] == 'generating'
    state = await repo.finish_turn(scope,sid,tid,UUID(turn['executionToken']),{'status':'stale','previewSnapshot':{'title':'invalid'}})
    assert state['previewSnapshot'] == {'title':'previous'}
    assert state['appliedSnapshot'] == {'title':'baseline'}
    assert (await repo.get_turn(scope,sid,tid))['status'] == 'stale'
    state, second, _ = await repo.reserve_turn(scope,sid,'two','b'*64,state['revision'],{})
    state = await repo.finish_turn(scope,sid,UUID(second['id']),UUID(second['executionToken']),{'status':'preview','previewSnapshot':{'title':'valid'}})
    assert state['previewSnapshot'] == {'title':'valid'}
    state = await repo.apply_version(scope,sid,state['revision'],uuid4(),{'title':'applied'})
    assert state['appliedSnapshot'] == {'title':'applied'}
    assert (await repo.get_version(scope,sid,UUID(state['currentVersionId'])))['snapshot'] == {'title':'applied'}
    other = ConversationScope(uuid4(),scope.project_id,'suite','professional')
    assert await repo.get_turn(other,sid,tid) is None
    assert await repo.get_version(other,sid,UUID(state['currentVersionId'])) is None


@pytest.mark.asyncio
async def test_answer_checks_latest_snapshot_at_completion_and_retains_preview():
    from backend.app.application.idempotency import request_fingerprint
    repo = MemoryPlanningConversationRepository()
    scope = ConversationScope(uuid4(), uuid4(), 'suite', 'regular')
    snapshot = {'title': 'original'}
    state = await repo.ensure_session(scope, dict(currentSnapshot=snapshot, input={'brief': 'old'}, previewSnapshot={'title': 'pending'}, previewPlanId='pending'))
    sid = UUID(state['id'])
    state, turn, _ = await repo.reserve_turn(scope, sid, 'question', 'a'*64, state['revision'], dict(currentFingerprint=request_fingerprint(snapshot), input={'brief': 'old'}))
    state = await repo.sync_snapshot(scope, sid, state['revision'], {'title': 'manual'}, {'brief': 'new'})
    state = await repo.finish_turn(scope, sid, UUID(turn['id']), turn['executionToken'], dict(status='completed', kind='answer', message='Based on original plan'))
    assert (await repo.get_turn(scope, sid, UUID(turn['id'])))['status'] == 'stale'
    assert state['currentSnapshot'] == {'title': 'manual'}
    assert state['previewSnapshot'] == {'title': 'pending'}
    assert state['previewPlanId'] == 'pending'
    assert state['activeTurnId'] is None
