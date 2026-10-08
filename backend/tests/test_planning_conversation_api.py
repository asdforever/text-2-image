from uuid import UUID, uuid4
import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend.app.core.errors import AppError
from backend.app.routes.planning_conversations import planning_conversation_router
from backend.tests.test_planning_conversation_service import setup

@pytest.mark.asyncio
async def test_real_routes_project_scope_background_and_replay():
    f,s,snap,session=await setup()
    app=FastAPI();app.state.planning_conversation_service=s;app.include_router(planning_conversation_router)
    @app.exception_handler(AppError)
    async def error(request:Request,exc:AppError):
        return JSONResponse(status_code=exc.status_code,content={'code':exc.code})
    f.master.result=dict(kind='clarification',message='改哪一项？',operations=[])
    url=f'/api/projects/{f.project_id}/planning-conversations'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get(url,params=dict(mode='hero',creationMode='regular'))).json()['data'] is None
        payload=dict(expectedRevision=session['revision'],text='不满意',input=f.input.model_dump(mode='json'),snapshot=snap)
        endpoint=url+'/'+session['id']+'/turns'
        assert (await client.post(endpoint,json=payload)).status_code==400
        result=await client.post(endpoint,json=payload,headers={'Idempotency-Key':'api'})
        assert result.status_code==202
        tid=result.json()['data']['turn']['id']
        poll=await client.get(endpoint+'/'+tid)
        assert poll.json()['data']['status']=='clarification'
        replay=await client.post(endpoint,json=payload,headers={'Idempotency-Key':'api'})
        assert replay.status_code==202
        assert len(f.master.calls)==2
        assert (await client.post(endpoint,json={**payload,'text':'changed'},headers={'Idempotency-Key':'api'})).status_code==409
        assert (await client.post(endpoint,json=payload,headers={'Idempotency-Key':'new'})).status_code==409
        assert (await client.get(endpoint.replace(str(f.project_id),str(uuid4()))+'/'+tid)).status_code==404
        assert (await client.get(url+'/'+session['id']+'/messages')).json()['data']['items']
@pytest.mark.asyncio
@pytest.mark.parametrize('sidecar',[{'parameterOverrides':{'missing':[]}},{'regularOptions':{'suite-hero':{'copyMode':'approved'}}},{'taskDesignOverrides':{'missing':{'productPresence':'auto'}}},{'taskDesignOverrides':{'suite-hero':{'productPresence':'invented'}}}])
async def test_invalid_snapshot_sidecar_returns_controlled_http_error(sidecar):
    f,s,snap,session=await setup();snap.update(sidecar)
    app=FastAPI();app.state.planning_conversation_service=s;app.include_router(planning_conversation_router)
    @app.exception_handler(AppError)
    async def error(request:Request,exc:AppError):
        return JSONResponse(status_code=exc.status_code,content={'code':exc.code})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        response=await client.post(f'/api/projects/{f.project_id}/planning-conversations/{session["id"]}/sync',json=dict(expectedRevision=session['revision'],input=f.input.model_dump(mode='json'),snapshot=snap))
        assert response.status_code==400
        assert response.json()['code']=='CONVERSATION_SNAPSHOT_INVALID'
