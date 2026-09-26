from uuid import UUID
from fastapi import APIRouter, Header, Query, Request, Response

from ..application.long_image_rendering import LongImageRecipe
from ..core.http import success_response

long_image_router = APIRouter()


@long_image_router.get("/api/projects/{project_id}/long-images")
async def list_long_images(project_id: UUID, request: Request):
    return success_response(await request.app.state.long_image_service.list(project_id))


@long_image_router.post("/api/projects/{project_id}/long-images", status_code=201)
async def save_long_image(project_id: UUID, payload: LongImageRecipe, request: Request,
                          idempotency_key: str = Header(min_length=1, max_length=200, alias="Idempotency-Key")):
    return success_response(await request.app.state.long_image_service.save(project_id, payload, idempotency_key))


@long_image_router.get("/api/projects/{project_id}/long-images/{asset_id}/download")
async def download_long_image(project_id: UUID, asset_id: UUID, request: Request, sliceHeight: int | None = Query(default=None, ge=256, le=10000)):
    body, mime, filename = await request.app.state.long_image_service.download(project_id, asset_id, sliceHeight)
    return Response(content=body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
