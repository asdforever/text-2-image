"""Opt-in checks against an already migrated DB; never apply migrations here."""
import asyncio
import os
from urllib.parse import urlsplit
from uuid import UUID, uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from backend.app.core.config import Settings
from backend.app.db import create_engine
from backend.app.application.planning_conversation_models import ConversationScope
from backend.app.planning_conversation_repository import PostgresPlanningConversationRepository
from backend.app.core.errors import AppError

@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv('PICAGENT_CONVERSATION_DB_CHECK') != '1', reason='Explicitly enable rollback database check after migration')
async def test_restart_cas_token_versions_scope_and_project_cascade_rollback():
    engine = create_engine(Settings().database_url)
    workspace, project = uuid4(), uuid4()
    scope = ConversationScope(workspace,project,'suite','regular')
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text("INSERT INTO suite_workbench.workspaces(id,name) VALUES (:id,'conversation rollback test')"),{'id':workspace})
                await connection.execute(text("INSERT INTO project_workbench.projects(id,workspace_id,name) VALUES (:id,:workspace,'conversation rollback test')"),{'id':project,'workspace':workspace})
                sessions = async_sessionmaker(connection,expire_on_commit=False,join_transaction_mode='create_savepoint')
                repo = PostgresPlanningConversationRepository(sessions)
                state = await repo.ensure_session(scope,{'currentSnapshot':{'title':'original'}})
                sid = UUID(state['id'])
                state, turn, owner = await repo.reserve_turn(scope,sid,'one','a'*64,state['revision'],{'text':'edit','frozenSnapshot':{'title':'original'}})
                assert owner
                restarted = PostgresPlanningConversationRepository(sessions)
                assert (await restarted.list_turns(scope,sid,None,10))['items'][0]['document']['frozenSnapshot'] == {'title':'original'}
                assert await restarted.get_session(ConversationScope(uuid4(),project,'suite','regular'),sid) is None
                replay = await restarted.reserve_turn(scope,sid,'one','a'*64,1,{})
                assert not replay[2] and replay[1]['id'] == turn['id']
                with pytest.raises(AppError) as error:
                    await restarted.finish_turn(scope,sid,UUID(turn['id']),uuid4(),{})
                assert error.value.code == 'TURN_TOKEN_MISMATCH'
                assert (await restarted.get_session(scope,sid))['revision'] == state['revision']
                plan = uuid4()
                state = await restarted.finish_turn(scope,sid,UUID(turn['id']),UUID(turn['executionToken']),{'status':'completed','previewPlanId':str(plan),'previewSnapshot':{'title':'candidate'}})
                state = await repo.apply_version(scope,sid,state['revision'],plan,{'title':'candidate'})
                v1 = state['currentVersionId']
                state = await restarted.apply_version(scope,sid,state['revision'],uuid4(),{'title':'restored'},UUID(v1))
                versions = (await PostgresPlanningConversationRepository(sessions).list_versions(scope,sid,None,10))['items']
                assert [v['versionNumber'] for v in versions] == [2,1]
                assert versions[0]['restoredFromVersionId'] == v1
                assert versions[1]['snapshot'] == {'title':'candidate'}
                with pytest.raises(AppError) as error:
                    await repo.sync_snapshot(scope,sid,1,{})
                assert error.value.code == 'REVISION_CONFLICT'
                await connection.execute(text('DELETE FROM project_workbench.projects WHERE id=:id'),{'id':project})
                for table in ('planning_conversations','planning_conversation_turns','planning_conversation_versions'):
                    column = 'project_id' if table == 'planning_conversations' else 'session_id'
                    assert await connection.scalar(text(f'SELECT count(*) FROM project_workbench.{table} WHERE {column}=:id'),{'id':project if column=='project_id' else sid}) == 0
            finally:
                await transaction.rollback()
        async with engine.connect() as connection:
            assert await connection.scalar(text('SELECT count(*) FROM suite_workbench.workspaces WHERE id=:id'),{'id':workspace}) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.getenv('PICAGENT_MIGRATION_TEST_DATABASE_URL') or os.getenv('PICAGENT_CONVERSATION_DB_CHECK') != '1', reason='Requires explicit switch and dedicated already migrated test database')
async def test_concurrent_reservation_has_one_owner_across_connections():
    url = os.environ['PICAGENT_MIGRATION_TEST_DATABASE_URL']
    assert 'test' in urlsplit(url).path.lower(), 'Only dedicated test databases allowed'
    engine = create_engine(url)
    sessions = async_sessionmaker(engine,expire_on_commit=False)
    workspace, project = uuid4(), uuid4()
    scope = ConversationScope(workspace,project,'hero','professional')
    try:
        async with sessions() as db, db.begin():
            await db.execute(text("INSERT INTO suite_workbench.workspaces(id,name) VALUES (:id,'conversation concurrency test')"),{'id':workspace})
            await db.execute(text("INSERT INTO project_workbench.projects(id,workspace_id,name) VALUES (:id,:workspace,'conversation concurrency test')"),{'id':project,'workspace':workspace})
        repo = PostgresPlanningConversationRepository(sessions)
        states = await asyncio.gather(repo.ensure_session(scope,{}),repo.ensure_session(scope,{}))
        assert states[0]['id'] == states[1]['id']
        sid = UUID(states[0]['id'])
        results = await asyncio.gather(*[PostgresPlanningConversationRepository(sessions).reserve_turn(scope,sid,'race','a'*64,1,{'text':'edit'}) for _ in range(4)])
        assert sum(result[2] for result in results) == 1
        assert len({result[1]['id'] for result in results}) == 1
    finally:
        async with sessions() as db, db.begin():
            await db.execute(text('DELETE FROM project_workbench.projects WHERE id=:id'),{'id':project})
            await db.execute(text('DELETE FROM suite_workbench.workspaces WHERE id=:id'),{'id':workspace})
        await engine.dispose()
