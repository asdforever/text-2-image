"""Conversation orchestration: frozen turns, immutable candidates and applied versions."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4
from pydantic import ValidationError
from ..core.errors import AppError
from .idempotency import request_fingerprint
from .module_planning_service import ModulePlanInput, MasterOutput, RegularOutput, RegularModule
from .runtime_module_catalog import runtime_module_catalog
from .regular_design import RegularTaskOptions
from .task_design import TaskDesignInput
from .planning_conversation_models import *
from .planning_conversation_patch import apply_operations, diff_snapshots, merge_candidate
from .planning_conversation_planner import PlanningConversationPlanner

class PlanningConversationService:
    def __init__(self, repository, module_planning_service):
        self.repository, self.module = repository, module_planning_service
        self.planner = PlanningConversationPlanner(self.module)
        self.executing = set()

    def scope(self, project, mode, creation_mode):
        return ConversationScope(self.module.workspace, project, mode, creation_mode)

    async def _project(self, project):
        record = await self.module.projects.get_project(project, self.module.workspace)
        if not record or record.status != 'active':
            raise AppError('INVALID_PROJECT_ID','项目不存在',404)

    async def _session(self, project, sid):
        await self._project(project)
        for mode in ('hero','suite'):
            for creation in ('regular','professional'):
                scope = self.scope(project,mode,creation)
                row = await self.repository.get_session(scope,sid)
                if row:
                    return scope,row
        raise AppError('CONVERSATION_NOT_FOUND','会话不存在',404)

    def _input(self, scope, payload):
        if len(set(payload.sourceAssetIds)) != len(payload.sourceAssetIds) or (payload.mode == 'suite' and len(payload.sourceAssetIds)>4):
            raise AppError('MODULE_PLAN_INVALID_INPUT','Invalid or duplicate source assets',400)
        if len(set(payload.referenceAssetIds))!=len(payload.referenceAssetIds) or set(payload.sourceAssetIds)&set(payload.referenceAssetIds):
            raise AppError('MODULE_PLAN_INVALID_INPUT','Invalid or overlapping reference assets',400)
        if payload.mode != scope.mode or payload.creationMode != scope.creation_mode or payload.reverseVersionId:
            raise AppError('CONVERSATION_SCOPE_MISMATCH','会话类型不匹配或反推不支持对话',400)

    @staticmethod
    def _body(model, data):
        try:
            return model.model_validate(data)
        except (ValidationError, ValueError, TypeError, KeyError) as exc:
            raise AppError('CONVERSATION_SNAPSHOT_INVALID', '当前方案或参数格式无效，请检查后重试', 400) from None

    async def _validate(self, scope, payload, snapshot, *, prepare=True):
        try:
            return await self._validate_snapshot(scope, payload, snapshot, prepare=prepare)
        except AppError as exc:
            if exc.code != 'MODULE_PLANNER_INVALID_RESPONSE':
                raise
            raise AppError('CONVERSATION_SNAPSHOT_INVALID', '当前方案未通过规则校验，请检查后重试', 400) from None
        except (ValidationError, ValueError, TypeError, KeyError, AttributeError):
            raise AppError('CONVERSATION_SNAPSHOT_INVALID', '当前方案或参数格式无效，请检查后重试', 400) from None

    async def _validate_snapshot(self, scope, payload, snapshot, *, prepare=True):
        self._input(scope,payload)
        plan = snapshot['plan']
        if plan.get('mode',scope.mode) != scope.mode or plan.get('creationMode',scope.creation_mode) != scope.creation_mode:
            raise AppError('CONVERSATION_SCOPE_MISMATCH','方案类型不匹配',400)
        published = await self.module.config.get_published()
        catalog = runtime_module_catalog(published.content,scope.mode)
        if scope.creation_mode == 'regular':
            fields = RegularOutput.model_fields
            raw = {k:plan[k] for k in fields if k in plan}
            module_fields = RegularModule.model_fields
            raw['modules'] = [{k:v for k,v in m.items() if k in module_fields} for m in plan['modules']]
            selected = [dict(taskId=m.get('taskId') or m['moduleId'],moduleId=m['moduleId']) for m in raw['modules']]
            effective = EffectiveRegularOutput.model_validate(raw).model_dump()
            self.module._validate_regular_selection(payload.model_copy(update={'selectedModules':selected}),catalog,effective['modules'])
        else:
            raw = {k:plan[k] for k in MasterOutput.model_fields if k in plan}
            self.module._validate_output(raw,scope.mode,catalog)
        ids = {m.get('taskId') or m['moduleId'] for m in plan['modules']}
        if scope.creation_mode == 'professional' and snapshot.get('regularOptions'):
            raise ValueError('Regular options require regular mode')
        if scope.creation_mode == 'regular' and snapshot.get('taskDesignOverrides'):
            raise ValueError('Task design overrides require professional mode')
        for task, design in snapshot.get('taskDesignOverrides',{}).items():
            if task not in ids:
                raise ValueError('Unknown task design task')
            TaskDesignInput.model_validate(design)
        for task, options in snapshot.get('regularOptions',{}).items():
            if task not in ids: raise ValueError('Unknown options task')
            RegularTaskOptions.model_validate(options)
        for task, rows in snapshot.get('parameterOverrides',{}).items():
            if task not in ids: raise ValueError('Unknown parameter task')
            if len(rows)>20 or any(set(r)!={'key','value'} or not isinstance(r['key'],str) or not isinstance(r['value'],str) or len(r['key'])>60 or len(r['value'])>500 for r in rows):
                raise ValueError('Invalid custom parameters')
        # Submission prepares the actual turn immediately after this validation.
        # Other callers also validate materials and model/rule context here.
        if prepare:
            return await self.planner.prepare(scope.project_id,payload,snapshot,'',[],workspace_id=scope.workspace_id)

    async def _decorate(self, scope, row):
        turns = await self.repository.list_turns(scope,UUID(row['id']),None,20)
        row['currentTurn'] = turns['items'][0] if turns['items'] else None
        row['messages'] = self._messages(turns['items'])
        row['diff'] = diff_snapshots(row.get('appliedSnapshot') or row.get('currentSnapshot'),row['previewSnapshot']) if row.get('previewSnapshot') else []
        row['appliedPlanId'],row['pendingPlanId'] = row.get('currentPlanId'),row.get('previewPlanId')
        row['snapshot'],row['planId'],row['versionId'] = row.get('currentSnapshot'),row.get('currentPlanId'),row.get('currentVersionId')
        return row

    @staticmethod
    def _messages(turns):
        messages=[]
        for turn in reversed(turns):
            messages.append(dict(id=turn['id']+':user',turnId=turn['id'],role='user',text=turn['document'].get('text','')))
            result=turn.get('result',{})
            if result.get('message') or result.get('error'):
                messages.append(dict(id=turn['id']+':assistant',turnId=turn['id'],role='assistant',text=result.get('message') or result['error']['message'],status=turn['status']))
        return messages

    async def get(self,project,mode,creation_mode):
        await self._project(project)
        scope=self.scope(project,mode,creation_mode)
        row=await self.repository.find_session(scope)
        if row and row.get('activeTurnId'):
            turn=await self.repository.get_turn(scope,UUID(row['id']),UUID(row['activeTurnId']))
            if (datetime.now(timezone.utc)-datetime.fromisoformat(turn['createdAt'])).total_seconds()>540:
                await self.repository.finish_turn(scope,UUID(row['id']),UUID(turn['id']),turn['executionToken'],dict(status='failed',error=dict(code='CONVERSATION_INTERRUPTED',message='规划超时或中断，请重试')))
                row=await self.repository.find_session(scope)
        return await self._decorate(scope,row) if row else None

    async def bootstrap(self,project,data):
        body=self._body(BootstrapInput,data)
        await self._project(project)
        scope=self.scope(project,body.mode,body.creationMode)
        self._input(scope,body.input)
        if body.snapshot is None:
            raise AppError('INITIAL_PLAN_REQUIRED','请先完成自动规划，再导入当前方案',409)
        existing=await self.repository.find_session(scope)
        if existing:return await self._decorate(scope,existing)
        if body.snapshot:
            snap=body.snapshot.model_dump(mode='json')
            try:
                plan_id=UUID(snap['plan']['id'])
            except (ValueError, TypeError, KeyError, AttributeError):
                raise AppError('CONVERSATION_SNAPSHOT_INVALID','方案标识无效',400) from None
            plan=await self.module.get(project,plan_id)
            if plan['status']!='completed' or plan['mode']!=body.mode or plan.get('creationMode','professional')!=body.creationMode or plan.get('origin')=='planning_conversation':
                raise AppError('MODULE_PLAN_NOT_READY','不可导入此规划',409)
        else:
            raise AppError('INITIAL_PLAN_REQUIRED','请先完成自动规划，再导入当前方案',409)
        await self._validate(scope,body.input,snap)
        row=await self.repository.ensure_session(scope,dict(currentSnapshot=snap,appliedSnapshot=snap,currentPlanId=plan['id'],input=body.input.model_dump(mode='json')))
        return await self._decorate(scope,row)

    async def sync(self,project,sid,data):
        body=self._body(SyncInput,data);scope,row=await self._session(project,sid)
        snap=body.snapshot.model_dump(mode='json');await self._validate(scope,body.input,snap)
        row=await self.repository.sync_snapshot(scope,sid,body.expectedRevision,snap,body.input.model_dump(mode='json'))
        return await self._decorate(scope,row)

    async def submit_turn(self,project,sid,data,key):
        body=self._body(FeedbackInput,data);scope,row=await self._session(project,sid)
        self._input(scope,body.input)
        if not key or not key.strip() or len(key)>200:raise AppError('INVALID_IDEMPOTENCY_REQUEST','幂等键无效',400)
        fingerprint=request_fingerprint(body.model_dump(mode='json'))
        # Replay before CAS and before loading mutable model/config context.
        pages=await self.repository.list_turns(scope,sid,None,100)
        recent_turns=pages['items'][:20]
        while True:
            for turn in pages['items']:
                if turn['requestKey']==key:
                    if turn['fingerprint']!=fingerprint:raise AppError('IDEMPOTENCY_KEY_REUSED','幂等键已使用',409)
                    return dict(session=await self._decorate(scope,row),turn=turn,owner=False)
            if not pages['nextCursor']:break
            pages=await self.repository.list_turns(scope,sid,UUID(pages['nextCursor']),100)
        manual=body.snapshot.model_dump(mode='json')
        await self._validate(scope,body.input,manual,prepare=False)
        base=merge_candidate(row['currentSnapshot'],manual,row['previewSnapshot']) if row.get('previewSnapshot') else manual
        planner,request,frozen,catalog=await self.planner.prepare(project,body.input,base,body.text,self._messages(recent_turns))
        document=dict(text=body.text,input=body.input.model_dump(mode='json'),manualSnapshot=manual,baseSnapshot=base,frozen=frozen,catalog=catalog,currentFingerprint=request_fingerprint(manual))
        row,turn,owner=await self.repository.reserve_turn(scope,sid,key,fingerprint,body.expectedRevision,document)
        return dict(session=await self._decorate(scope,row),turn=turn,owner=owner)

    async def run_turn(self,scope,sid,tid):
        turn=await self.repository.get_turn(scope,sid,tid)
        if not turn or turn['status']!='generating' or tid in self.executing:return
        self.executing.add(tid);doc=turn['document']
        try:
            async with asyncio.timeout(540):
                payload=ModulePlanInput.model_validate(doc['input'])
                planner,request,now,catalog=await self.planner.prepare(scope.project_id,payload,doc['baseSnapshot'],doc['text'],[],workspace_id=scope.workspace_id)
                from .module_planning_service import ModuleMasterRequest
                request=ModuleMasterRequest(doc['frozen']['systemPrompt'],doc['frozen']['userPrompt'],request.image_inputs,request.image_mime_types)
                reply=Reply.model_validate(await planner.plan_modules(request))
                _,_,completed_context,_=await self.planner.prepare(scope.project_id,payload,doc['baseSnapshot'],doc['text'],[],workspace_id=scope.workspace_id)
                row=await self.repository.get_session(scope,sid)
                stale=row.get('input')!=doc['input'] or request_fingerprint(row['currentSnapshot'])!=doc['currentFingerprint'] or any(now.get(k)!=doc['frozen'].get(k) or completed_context.get(k)!=doc['frozen'].get(k) for k in ('sourceAssets','referenceAssets','generationConfig','promptModelConnection','planningEngine','skill','runtimeModules','selectedStyle'))
                result=dict(status='stale' if stale else ('completed' if reply.kind=='answer' else 'clarification'),kind=reply.kind,message=reply.message)
                if reply.kind=='revision':
                    candidate=apply_operations(doc['baseSnapshot'],[op.model_dump(mode='json') for op in reply.operations])
                    await self._validate(scope,payload,candidate)
                    candidate['plan']['input']=doc['input']
                    plan=await self._candidate(scope,sid,candidate,doc['frozen'],tid)
                    candidate['plan']=plan
                    result.update(status='stale' if stale else 'preview',previewSnapshot=candidate,previewPlanId=plan['id'],baseSnapshot=doc['manualSnapshot'],input=doc['input'],diff=diff_snapshots(row.get('appliedSnapshot') or doc['manualSnapshot'],candidate))
                await self.repository.finish_turn(scope,sid,tid,turn['executionToken'],result)
        except BaseException as exc:
            error=exc if isinstance(exc,AppError) else AppError('CONVERSATION_FAILED','规划失败、超时或违反当前规则，请调整要求后重试',502)
            await self.repository.finish_turn(scope,sid,tid,turn['executionToken'],dict(status='failed',error=dict(code=error.code,message=error.message)))
            if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
        finally:self.executing.discard(tid)

    async def _candidate(self,scope,sid,snapshot,frozen,key):
        plan=deepcopy(snapshot['plan'])
        plan.update(origin='planning_conversation',sessionId=str(sid),parentPlanId=plan.get('id'),status='planning',mode=scope.mode,creationMode=scope.creation_mode,snapshot=frozen)
        value,_=await self.module.repository.create(scope.workspace_id,scope.project_id,'conversation:'+str(key),request_fingerprint(snapshot),plan)
        value['status']='completed'
        return await self.module.repository.save(scope.workspace_id,scope.project_id,UUID(value['id']),value)

    async def apply(self,project,sid,data):
        body=self._body(ApplyInput,data);scope,row=await self._session(project,sid)
        if row.get('previewPlanId')!=str(body.candidatePlanId):raise AppError('CANDIDATE_NOT_CURRENT','候选已失效',409)
        turns=await self.repository.list_turns(scope,sid,None,100)
        preview=None
        while True:
            preview=next((t for t in turns['items'] if t.get('result',{}).get('previewPlanId')==str(body.candidatePlanId) and t['status']=='preview'),None)
            if preview or not turns['nextCursor']:break
            turns=await self.repository.list_turns(scope,sid,UUID(turns['nextCursor']),100)
        if not preview:raise AppError('CANDIDATE_NOT_CURRENT','候选已失效',409)
        if body.input.model_dump(mode='json')!=preview['result']['input']:raise AppError('PLANNING_CONTEXT_CHANGED','配置已变化，请重新规划',409)
        snapshot=merge_candidate(preview['result']['baseSnapshot'],body.snapshot.model_dump(mode='json'),row['previewSnapshot'])
        _,_,frozen,_=await self._validate(scope,body.input,snapshot)
        if any(frozen.get(k)!=preview['document']['frozen'].get(k) for k in ('sourceAssets','referenceAssets','generationConfig','promptModelConnection','planningEngine','skill','runtimeModules','selectedStyle')):
            raise AppError('PLANNING_CONTEXT_CHANGED','素材或规则已变化，请重新规划',409)
        plan_id=body.candidatePlanId
        if snapshot!=row['previewSnapshot']:
            plan=await self._candidate(scope,sid,snapshot,frozen,uuid4())
            snapshot['plan']=plan
            plan_id=UUID(plan['id'])
        return await self._decorate(scope,await self.repository.apply_version(scope,sid,body.expectedRevision,plan_id,snapshot))

    async def discard(self,project,sid,data):
        body=self._body(DiscardInput,data);scope,row=await self._session(project,sid)
        return await self._decorate(scope,await self.repository.discard_preview(scope,sid,body.expectedRevision))

    async def restore(self,project,sid,data):
        body=self._body(RestoreInput,data);scope,row=await self._session(project,sid)
        version=await self.repository.get_version(scope,sid,body.versionId)
        if not version:raise AppError('VERSION_NOT_FOUND','版本不存在',404)
        snapshot=deepcopy(version['snapshot'])
        await self._validate(scope,body.input,snapshot)
        saved=snapshot['plan'].get('snapshot',{})
        if saved.get('referenceAssets') and [x['assetId'] for x in saved['referenceAssets']]!=[str(x) for x in body.input.referenceAssetIds]:
            raise AppError('PLANNING_CONTEXT_CHANGED','Old version references differ from current input',409)
        if saved.get('sourceAssets') and [x['assetId'] for x in saved['sourceAssets']]!=[str(x) for x in body.input.sourceAssetIds]:
            raise AppError('PLANNING_CONTEXT_CHANGED','旧版本商品素材与当前输入不一致',409)
        return await self._decorate(scope,await self.repository.apply_version(scope,sid,body.expectedRevision,UUID(version['planId']),snapshot,body.versionId))

    async def turn(self,project,sid,tid):
        scope,row=await self._session(project,sid)
        await self.get(project,scope.mode,scope.creation_mode)
        turn=await self.repository.get_turn(scope,sid,tid)
        if not turn:raise AppError('TURN_NOT_FOUND','轮次不存在',404)
        return turn

    async def messages(self,project,sid,before=None,limit=20):
        scope,row=await self._session(project,sid)
        page=await self.repository.list_turns(scope,sid,before,limit)
        return dict(items=self._messages(page['items']),nextCursor=page['nextCursor'])

    async def versions(self,project,sid,before=None,limit=20):
        scope,row=await self._session(project,sid)
        return await self.repository.list_versions(scope,sid,before,limit)

    async def is_applied(self,workspace,project,plan):
        scope=ConversationScope(workspace,project,plan['mode'],plan['creationMode'])
        page=await self.repository.list_versions(scope,UUID(plan['sessionId']),None,100)
        while True:
            if any(v['planId']==plan['id'] for v in page['items']):return True
            if not page['nextCursor']:return False
            page=await self.repository.list_versions(scope,UUID(plan['sessionId']),UUID(page['nextCursor']),100)

    async def validate_applied_version(self, project, plan_id, version_id, mode):
        await self._project(project)
        if not plan_id:
            raise AppError('MODULE_PLAN_NOT_APPLIED', 'Applied version requires a plan', 409)
        plan = await self.module.get(project, UUID(str(plan_id)))
        if plan.get('mode') != mode or plan.get('origin') != 'planning_conversation':
            raise AppError('MODULE_PLAN_NOT_APPLIED', 'Applied version does not belong to this plan', 409)
        scope = self.scope(project, mode, plan['creationMode'])
        version = await self.repository.get_version(scope, UUID(plan['sessionId']), UUID(str(version_id)))
        if not version or version['planId'] != str(plan_id):
            raise AppError('MODULE_PLAN_NOT_APPLIED', 'Applied version does not belong to this plan', 409)
        return version
