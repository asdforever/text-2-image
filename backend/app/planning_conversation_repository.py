"""Scoped, revision checked conversation persistence; no model calls in transactions."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import UUID, uuid4
from sqlalchemy import text
from .core.errors import AppError


def _now():
    return datetime.now(timezone.utc).isoformat()


def _error(code, status=409):
    raise AppError(code, code, status)


class MemoryPlanningConversationRepository:
    def __init__(self):
        self.sessions = {}
        self.turns = {}
        self.versions = {}

    async def ensure_session(self, scope, initial):
        for row_scope, value in self.sessions.values():
            if row_scope == scope:
                return deepcopy(value)
        value = {**deepcopy(initial), 'id': str(uuid4()), 'revision': 1,
                 'workspaceId': str(scope.workspace_id), 'projectId': str(scope.project_id),
                 'mode': scope.mode, 'creationMode': scope.creation_mode,
                 'createdAt': _now(), 'updatedAt': _now()}
        for key in ('currentSnapshot', 'currentPlanId', 'currentVersionId', 'previewSnapshot', 'previewPlanId', 'activeTurnId', 'appliedSnapshot'):
            value.setdefault(key, None)
        self.sessions[UUID(value['id'])] = (scope, value)
        return deepcopy(value)

    async def find_session(self, scope):
        for row_scope, value in self.sessions.values():
            if row_scope == scope:
                return deepcopy(value)
        return None

    async def get_turn(self, scope, session_id, turn_id):
        if await self.get_session(scope, session_id) is None:
            return None
        turn = self.turns.get(turn_id)
        return deepcopy(turn) if turn and turn['sessionId'] == str(session_id) else None

    async def get_version(self, scope, session_id, version_id):
        if await self.get_session(scope, session_id) is None:
            return None
        version = self.versions.get(version_id)
        return deepcopy(version) if version and version['sessionId'] == str(session_id) else None

    async def get_session(self, scope, session_id):
        row = self.sessions.get(session_id)
        return deepcopy(row[1]) if row and row[0] == scope else None

    def _session(self, scope, sid, revision=None):
        row = self.sessions.get(sid)
        if not row or row[0] != scope:
            _error('CONVERSATION_NOT_FOUND', 404)
        value = row[1]
        if revision is not None and value['revision'] != revision:
            _error('REVISION_CONFLICT')
        return value

    def _bump(self, value):
        value['revision'] += 1
        value['updatedAt'] = _now()
        return deepcopy(value)

    async def reserve_turn(self, scope, session_id, key, fingerprint, expected_revision, document):
        value = self._session(scope, session_id)
        for turn in self.turns.values():
            if turn['sessionId'] == str(session_id) and turn['requestKey'] == key:
                if turn['fingerprint'] != fingerprint:
                    _error('IDEMPOTENCY_KEY_REUSED')
                return deepcopy(value), deepcopy(turn), False
        self._session(scope, session_id, expected_revision)
        if value['activeTurnId']:
            _error('CONVERSATION_BUSY')
        turn = {'id': str(uuid4()), 'sessionId': str(session_id), 'requestKey': key,
                'fingerprint': fingerprint, 'status': 'generating', 'executionToken': str(uuid4()),
                'document': deepcopy(document), 'createdAt': _now(), 'updatedAt': _now()}
        self.turns[UUID(turn['id'])] = turn
        if 'manualSnapshot' in document:
            value['currentSnapshot'] = deepcopy(document['manualSnapshot'])
        if 'input' in document:
            value['input'] = deepcopy(document['input'])
        value['activeTurnId'] = turn['id']
        return self._bump(value), deepcopy(turn), True

    async def finish_turn(self, scope, session_id, turn_id, token, result):
        value = self._session(scope, session_id)
        turn = self.turns.get(turn_id)
        if not turn or turn['sessionId'] != str(session_id):
            _error('TURN_NOT_FOUND', 404)
        if turn['executionToken'] != str(token):
            _error('TURN_TOKEN_MISMATCH')
        if turn['status'] != 'generating':
            return deepcopy(value)
        status = result.get('status', 'completed')
        if status not in ('completed', 'preview', 'failed', 'clarification', 'stale'):
            _error('INVALID_TURN_RESULT', 422)
        if (status in ('preview', 'clarification') or (status == 'completed' and result.get('kind') == 'answer')) and turn['document'].get('currentFingerprint'):
            from .application.idempotency import request_fingerprint
            if request_fingerprint(value['currentSnapshot']) != turn['document']['currentFingerprint'] or value.get('input') != turn['document'].get('input'):
                status = 'stale'
                result = {**result, 'status': status}
        turn.update(status=status, result=deepcopy(result), updatedAt=_now())
        if status in ('completed', 'preview'):
            for key in ('previewSnapshot', 'previewPlanId'):
                if key in result:
                    value[key] = deepcopy(result[key])
        value['activeTurnId'] = None
        return self._bump(value)

    async def sync_snapshot(self, scope, session_id, expected_revision, snapshot, input_document=None):
        value = self._session(scope, session_id, expected_revision)
        value['currentSnapshot'] = deepcopy(snapshot)
        if input_document is not None:
            value['input'] = deepcopy(input_document)
        return self._bump(value)

    async def apply_version(self, scope, session_id, expected_revision, plan_id, snapshot, restored_from_version_id=None):
        value = self._session(scope, session_id, expected_revision)
        if value['activeTurnId']:
            _error('CONVERSATION_BUSY')
        if restored_from_version_id:
            source = self.versions.get(restored_from_version_id)
            if not source or source['sessionId'] != str(session_id):
                _error('VERSION_NOT_FOUND', 404)
        existing = [v['versionNumber'] for v in self.versions.values() if v['sessionId'] == str(session_id)]
        version = {'id': str(uuid4()), 'sessionId': str(session_id), 'planId': str(plan_id),
                   'versionNumber': max(existing, default=0)+1, 'snapshot': deepcopy(snapshot),
                   'restoredFromVersionId': str(restored_from_version_id) if restored_from_version_id else None,
                   'createdAt': _now()}
        self.versions[UUID(version['id'])] = version
        value.update(appliedSnapshot=deepcopy(snapshot), currentSnapshot=deepcopy(snapshot), currentPlanId=str(plan_id), currentVersionId=version['id'], previewSnapshot=None, previewPlanId=None)
        return self._bump(value)

    async def discard_preview(self, scope, session_id, expected_revision):
        value = self._session(scope, session_id, expected_revision)
        if value['activeTurnId']:
            _error('CONVERSATION_BUSY')
        value.update(previewSnapshot=None, previewPlanId=None)
        return self._bump(value)

    def _page(self, scope, sid, before, limit, records):
        self._session(scope, sid)
        if not 1 <= limit <= 100:
            _error('INVALID_PAGE_LIMIT', 422)
        rows = sorted((v for v in records.values() if v['sessionId'] == str(sid)), key=lambda v: (v['createdAt'], v['id']), reverse=True)
        if before is not None:
            index = next((i for i,v in enumerate(rows) if v['id'] == str(before)), None)
            if index is None:
                _error('INVALID_PAGE_CURSOR', 422)
            rows = rows[index+1:]
        return {'items': deepcopy(rows[:limit]), 'nextCursor': rows[limit-1]['id'] if len(rows)>limit else None}

    async def list_turns(self, scope, session_id, before, limit):
        return self._page(scope,session_id,before,limit,self.turns)

    async def list_versions(self, scope, session_id, before, limit):
        return self._page(scope,session_id,before,limit,self.versions)


class PostgresPlanningConversationRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    def _params(scope):
        return dict(workspace=scope.workspace_id, project=scope.project_id, mode=scope.mode, creation=scope.creation_mode)

    async def ensure_session(self, scope, initial):
        memory = MemoryPlanningConversationRepository()
        value = await memory.ensure_session(scope, initial)
        params = {**self._params(scope), 'id': UUID(value['id']), 'document': json.dumps(value)}
        async with self.sessions() as db, db.begin():
            await db.execute(text('INSERT INTO project_workbench.planning_conversations (id,workspace_id,project_id,mode,creation_mode,revision,document) VALUES (:id,:workspace,:project,:mode,:creation,1,CAST(:document AS jsonb)) ON CONFLICT (workspace_id,project_id,mode,creation_mode) DO NOTHING'),params)
            raw = await db.scalar(text('SELECT document FROM project_workbench.planning_conversations WHERE workspace_id=:workspace AND project_id=:project AND mode=:mode AND creation_mode=:creation'),params)
            return deepcopy(raw)

    async def _run(self, scope, sid, method, *args):
        params = {**self._params(scope), 'id': sid}
        async with self.sessions() as db, db.begin():
            raw = await db.scalar(text('SELECT document FROM project_workbench.planning_conversations WHERE id=:id AND workspace_id=:workspace AND project_id=:project AND mode=:mode AND creation_mode=:creation FOR UPDATE'), params)
            if raw is None:
                if method in ('get_session','get_turn','get_version'):
                    return None
                _error('CONVERSATION_NOT_FOUND',404)
            memory = MemoryPlanningConversationRepository()
            memory.sessions[sid] = (scope,deepcopy(raw))
            for table, records in [('planning_conversation_turns',memory.turns),('planning_conversation_versions',memory.versions)]:
                rows = (await db.execute(text(f'SELECT id,document FROM project_workbench.{table} WHERE session_id=:id'),params)).mappings()
                for row in rows:
                    records[row['id']] = deepcopy(row['document'])
            original_turns = deepcopy(memory.turns)
            original_versions = deepcopy(memory.versions)
            result = await getattr(memory,method)(scope,sid,*args)
            if method in ('get_session','get_turn','get_version','list_turns','list_versions'):
                return result
            value = memory.sessions[sid][1]
            if value == raw:
                return result
            await db.execute(text('UPDATE project_workbench.planning_conversations SET revision=:revision,document=CAST(:document AS jsonb),updated_at=now() WHERE id=:id'),dict(id=sid,revision=value['revision'],document=json.dumps(value)))
            for turn in memory.turns.values():
                if original_turns.get(UUID(turn['id'])) == turn:
                    continue
                await db.execute(text('INSERT INTO project_workbench.planning_conversation_turns (id,session_id,request_key,fingerprint,status,execution_token,document) VALUES (:tid,:sid,:key,:fingerprint,:status,:token,CAST(:document AS jsonb)) ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,document=EXCLUDED.document,updated_at=now()'),dict(tid=UUID(turn['id']),sid=sid,key=turn['requestKey'],fingerprint=turn['fingerprint'],status=turn['status'],token=UUID(turn['executionToken']),document=json.dumps(turn)))
            for version in memory.versions.values():
                if UUID(version['id']) in original_versions:
                    continue
                await db.execute(text('INSERT INTO project_workbench.planning_conversation_versions (id,session_id,plan_id,version_number,snapshot,restored_from_version_id,document) VALUES (:vid,:sid,:plan,:number,CAST(:snapshot AS jsonb),:source,CAST(:document AS jsonb)) ON CONFLICT (id) DO NOTHING'),dict(vid=UUID(version['id']),sid=sid,plan=UUID(version['planId']),number=version['versionNumber'],snapshot=json.dumps(version['snapshot']),source=UUID(version['restoredFromVersionId']) if version['restoredFromVersionId'] else None,document=json.dumps(version)))
            return result

    async def find_session(self, scope):
        async with self.sessions() as db:
            sid = await db.scalar(text('SELECT id FROM project_workbench.planning_conversations WHERE workspace_id=:workspace AND project_id=:project AND mode=:mode AND creation_mode=:creation'),self._params(scope))
        return await self.get_session(scope, sid) if sid else None

    async def get_turn(self, scope, session_id, turn_id):
        return await self._run(scope,session_id,'get_turn',turn_id)

    async def get_version(self, scope, session_id, version_id):
        return await self._run(scope,session_id,'get_version',version_id)

    async def get_session(self, scope, session_id):
        return await self._run(scope,session_id,'get_session')

    async def reserve_turn(self, scope, session_id, key, fingerprint, expected_revision, document):
        return await self._run(scope,session_id,'reserve_turn',key,fingerprint,expected_revision,document)

    async def finish_turn(self, scope, session_id, turn_id, token, result):
        return await self._run(scope,session_id,'finish_turn',turn_id,token,result)

    async def sync_snapshot(self, scope, session_id, expected_revision, snapshot, input_document=None):
        return await self._run(scope,session_id,'sync_snapshot',expected_revision,snapshot,input_document)

    async def apply_version(self, scope, session_id, expected_revision, plan_id, snapshot, restored_from_version_id=None):
        return await self._run(scope,session_id,'apply_version',expected_revision,plan_id,snapshot,restored_from_version_id)

    async def discard_preview(self, scope, session_id, expected_revision):
        return await self._run(scope,session_id,'discard_preview',expected_revision)

    async def list_turns(self, scope, session_id, before, limit):
        return await self._run(scope,session_id,'list_turns',before,limit)

    async def list_versions(self, scope, session_id, before, limit):
        return await self._run(scope,session_id,'list_versions',before,limit)
