from typing import Literal
from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Header, Query, Request
from ..application.planning_conversation_models import BootstrapInput, SyncInput, FeedbackInput, ApplyInput, RestoreInput, DiscardInput
from ..core.http import success_response

planning_conversation_router=APIRouter(prefix='/api/projects/{project_id}/planning-conversations')

@planning_conversation_router.get('')
async def get_session(project_id:UUID,request:Request,mode:Literal['hero','suite'],creationMode:Literal['regular','professional']):
    return success_response(await request.app.state.planning_conversation_service.get(project_id,mode,creationMode))

@planning_conversation_router.post('/bootstrap')
async def bootstrap(project_id:UUID,payload:BootstrapInput,request:Request):
    return success_response(await request.app.state.planning_conversation_service.bootstrap(project_id,payload.model_dump(mode='json')))

@planning_conversation_router.post('/{session_id}/sync')
async def sync(project_id:UUID,session_id:UUID,payload:SyncInput,request:Request):
    return success_response(await request.app.state.planning_conversation_service.sync(project_id,session_id,payload.model_dump(mode='json')))

@planning_conversation_router.post('/{session_id}/turns',status_code=202)
async def submit(project_id:UUID,session_id:UUID,payload:FeedbackInput,request:Request,background_tasks:BackgroundTasks,idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    service=request.app.state.planning_conversation_service
    result=await service.submit_turn(project_id,session_id,payload.model_dump(mode='json'),idempotency_key or '')
    if result.pop('owner'):
        row=result['session'];scope=service.scope(project_id,row['mode'],row['creationMode'])
        background_tasks.add_task(service.run_turn,scope,session_id,UUID(result['turn']['id']))
    return success_response(result)

@planning_conversation_router.get('/{session_id}/turns/{turn_id}')
async def turn(project_id:UUID,session_id:UUID,turn_id:UUID,request:Request):
    return success_response(await request.app.state.planning_conversation_service.turn(project_id,session_id,turn_id))

@planning_conversation_router.get('/{session_id}/messages')
async def messages(project_id:UUID,session_id:UUID,request:Request,before:UUID|None=None,limit:int=Query(default=20,ge=1,le=100)):
    return success_response(await request.app.state.planning_conversation_service.messages(project_id,session_id,before,limit))

@planning_conversation_router.get('/{session_id}/versions')
async def versions(project_id:UUID,session_id:UUID,request:Request,before:UUID|None=None,limit:int=Query(default=20,ge=1,le=100)):
    return success_response(await request.app.state.planning_conversation_service.versions(project_id,session_id,before,limit))

@planning_conversation_router.post('/{session_id}/apply')
async def apply(project_id:UUID,session_id:UUID,payload:ApplyInput,request:Request):
    return success_response(await request.app.state.planning_conversation_service.apply(project_id,session_id,payload.model_dump(mode='json')))

@planning_conversation_router.post('/{session_id}/discard')
async def discard(project_id:UUID,session_id:UUID,payload:DiscardInput,request:Request):
    return success_response(await request.app.state.planning_conversation_service.discard(project_id,session_id,payload.model_dump(mode='json')))

@planning_conversation_router.post('/{session_id}/restore')
async def restore(project_id:UUID,session_id:UUID,payload:RestoreInput,request:Request):
    return success_response(await request.app.state.planning_conversation_service.restore(project_id,session_id,payload.model_dump(mode='json')))
