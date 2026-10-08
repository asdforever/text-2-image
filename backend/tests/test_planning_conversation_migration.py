from io import StringIO
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
REVISION = '20261008_planning_conversations'

def test_new_head_generates_reversible_conversation_schema_offline():
    output = StringIO()
    config = Config(str(ROOT / 'alembic.ini'), output_buffer=output)
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [REVISION]
    assert scripts.get_revision(REVISION).down_revision == '20261007_reverse_analysis_token'
    command.upgrade(config, '20261007_reverse_analysis_token:' + REVISION, sql=True)
    sql = output.getvalue()
    for table in ('planning_conversations','planning_conversation_turns','planning_conversation_versions'):
        assert 'CREATE TABLE project_workbench.' + table in sql
    assert 'UNIQUE (workspace_id, project_id, mode, creation_mode)' in sql
    assert 'UNIQUE (session_id, request_key)' in sql
    assert 'UNIQUE (session_id, version_number)' in sql
    assert 'revision > 0' in sql
    assert sql.count('ON DELETE CASCADE') >= 3
    output.truncate(0)
    output.seek(0)
    command.downgrade(config, REVISION + ':20261007_reverse_analysis_token', sql=True)
    assert output.getvalue().count('DROP TABLE project_workbench.planning_conversation') == 3

async def _readiness_for_revision(revision):
    from backend.app.postgres_repository import PostgresRepository
    class Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def execute(self, query):
            return None
        async def scalar(self, query):
            return revision if 'alembic_version' in str(query) else 0
    return await PostgresRepository(Session).readiness_checks()


def test_readiness_accepts_new_head_and_rejects_old_schema():
    import asyncio
    assert asyncio.run(_readiness_for_revision(REVISION)) == {'database':True,'schema':True,'workspaceScope':True}
    assert asyncio.run(_readiness_for_revision('20261007_reverse_analysis_token')) == {'database':True,'schema':False,'workspaceScope':False}
