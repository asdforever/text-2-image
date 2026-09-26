from fastapi import APIRouter, Request
from ..core.errors import AppError
from ..core.http import success_response

model_connection_router = APIRouter(prefix="/api/model-connections")


@model_connection_router.get("")
async def list_connections(request: Request):
    return success_response(await request.app.state.model_connection_service.list())


@model_connection_router.post("", status_code=201)
async def create_connection(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        raise AppError("MODEL_CONNECTION_INVALID", "模型连接请求格式无效", 400) from None
    return success_response(await request.app.state.model_connection_service.create(payload))
