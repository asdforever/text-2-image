from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, Request

from ..core.errors import AppError
from ..core.http import success_response


style_harmonization_router = APIRouter()


def _project_id(value):
    try:
        return UUID(value)
    except ValueError:
        raise AppError("STYLE_PROJECT_INVALID", "项目标识无效", 400) from None


async def _payload(request):
    try:
        payload = await request.json()
    except ValueError:
        raise AppError("STYLE_REQUEST_INVALID", "风格统一请求格式无效", 400) from None
    allowed = {"assetIds", "mode", "referenceAssetId", "promptVersionId", "prompt", "expectedPreviewHash"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise AppError("STYLE_REQUEST_INVALID", "风格统一请求字段无效", 400)
    return payload


@style_harmonization_router.post("/api/projects/{project_id}/style-harmonizations/preview")
async def preview(project_id: str, request: Request):
    payload = await _payload(request)
    return success_response(await request.app.state.style_harmonization_service.preview(_project_id(project_id), payload))


@style_harmonization_router.post("/api/projects/{project_id}/style-harmonizations", status_code=202)
async def harmonize(project_id: str, request: Request, background: BackgroundTasks, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    payload = await _payload(request)
    expected_hash = payload.get("expectedPreviewHash")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64 or any(char not in "0123456789abcdef" for char in expected_hash):
        raise AppError("STYLE_PREVIEW_REQUIRED", "请先预览并确认风格统一任务", 409)
    service = request.app.state.style_harmonization_service
    resolved_id = _project_id(project_id)
    job = await service.submit(resolved_id, payload, idempotency_key)
    if job["status"] == "queued":
        background.add_task(service.execute, resolved_id, job["id"])
    return success_response(job)


@style_harmonization_router.get("/api/projects/{project_id}/style-harmonizations")
async def list_harmonizations(project_id: str, request: Request):
    return success_response(await request.app.state.style_harmonization_service.list_jobs(_project_id(project_id)))
