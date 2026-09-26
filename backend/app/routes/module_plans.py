from uuid import UUID
from fastapi import APIRouter, Header, Query, Request
from ..application.module_planning_service import ModulePlanInput
from ..core.errors import AppError
from ..core.http import success_response

module_plan_router = APIRouter(prefix="/api/projects/{project_id}/module-plans")

@module_plan_router.post("", status_code=201)
async def create_module_plan(project_id: UUID, payload: ModulePlanInput, request: Request,
                             idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    result = await request.app.state.module_planning_service.plan(project_id, payload, idempotency_key or "")
    return success_response(result)

@module_plan_router.get("/latest")
async def get_latest_module_plan(project_id: UUID, request: Request, mode: str = Query(...)):
    if mode not in {"hero", "suite"}:
        raise AppError("MODULE_PLAN_INVALID_INPUT", "规划类型无效", 400)
    return success_response(await request.app.state.module_planning_service.latest(project_id, mode))

@module_plan_router.get("/{plan_id}")
async def get_module_plan(project_id: UUID, plan_id: UUID, request: Request):
    return success_response(await request.app.state.module_planning_service.get(project_id, plan_id))
