from fastapi import APIRouter, Header, Request

from ..core.errors import AppError
from ..core.http import success_response
from ..schemas import GenerationConfigDraftReplace


generation_config_router = APIRouter(prefix="/api/generation-config")


@generation_config_router.get("/planning-capabilities")
async def get_planning_capabilities():
    return success_response({
        "workflow": "unified-module-v2", "styleCallsPerPlan": 0, "moduleCallsPerModule": 1,
    })


def _version_view(version) -> dict:
    return {
        "id": str(version.id),
        "version": version.version_no,
        "content": version.content,
        "contentSha256": version.content_sha256,
        "createdAt": version.created_at.isoformat(),
    }


def _draft_view(draft) -> dict:
    return {
        "baseVersion": draft.base_version_no,
        "content": draft.content,
        "updatedAt": draft.updated_at.isoformat(),
    }


@generation_config_router.get("")
async def get_generation_config(request: Request):
    version = await request.app.state.generation_config_service.get_published()
    return success_response(_version_view(version))


@generation_config_router.get("/draft")
async def get_generation_config_draft(request: Request):
    draft = await request.app.state.generation_config_service.get_draft()
    return success_response(_draft_view(draft))


@generation_config_router.put("/draft")
async def replace_generation_config_draft(
    payload: GenerationConfigDraftReplace,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    draft = await request.app.state.generation_config_service.replace_draft(
        payload.content, payload.baseVersion, idempotency_key
    )
    return success_response(_draft_view(draft))


@generation_config_router.delete("/draft")
async def discard_generation_config_draft(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    draft = await request.app.state.generation_config_service.discard_draft(
        idempotency_key
    )
    return success_response(_draft_view(draft))


@generation_config_router.post("/publish")
async def publish_generation_config(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    version = await request.app.state.generation_config_service.publish(idempotency_key)
    return success_response(_version_view(version))


@generation_config_router.get("/versions/{version_no}")
async def get_generation_config_version(version_no: int, request: Request):
    if version_no < 1:
        raise AppError(
            "GENERATION_CONFIG_VERSION_NOT_FOUND",
            "生成配置版本不存在",
            404,
        )
    version = await request.app.state.generation_config_service.get_version(version_no)
    if version is None:
        raise AppError(
            "GENERATION_CONFIG_VERSION_NOT_FOUND",
            "生成配置版本不存在",
            404,
        )
    return success_response(_version_view(version))


@generation_config_router.get("/resolve")
async def resolve_generation_config(request: Request):
    resolved = await request.app.state.generation_config_service.resolve_published()
    return success_response(resolved)
