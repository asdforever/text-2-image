from fastapi import APIRouter, Request

from ..core.http import success_response


asset_router = APIRouter()


@asset_router.get("/api/asset-libraries")
async def list_asset_libraries(request: Request):
    return success_response(await request.app.state.asset_service.list_libraries())


@asset_router.post("/api/asset-libraries", status_code=201)
async def create_asset_library(payload: dict, request: Request):
    return success_response(await request.app.state.asset_service.create_library(payload))


@asset_router.get("/api/asset-libraries/{library_id}")
async def get_asset_library(library_id: str, request: Request):
    return success_response(await request.app.state.asset_service.get_library(library_id))


@asset_router.patch("/api/asset-libraries/{library_id}")
async def update_asset_library(library_id: str, payload: dict, request: Request):
    return success_response(
        await request.app.state.asset_service.update_library(library_id, payload)
    )


@asset_router.delete("/api/asset-libraries/{library_id}", status_code=204)
async def delete_asset_library(library_id: str, request: Request):
    await request.app.state.asset_service.delete_library(library_id)


@asset_router.get("/api/asset-libraries/{library_id}/assets")
async def list_assets(library_id: str, request: Request):
    return success_response(await request.app.state.asset_service.list_assets(library_id))


@asset_router.post("/api/asset-libraries/{library_id}/assets", status_code=201)
async def create_asset(library_id: str, request: Request):
    form = await request.form()
    file = form.get("file")
    upload = file if hasattr(file, "read") and hasattr(file, "filename") else None
    payload = {
        "name": form.get("name"),
        "content": form.get("content"),
        "metadata": form.get("metadata"),
        "fileData": await upload.read() if upload else None,
        "filename": upload.filename if upload else None,
        "contentType": upload.content_type if upload else None,
    }
    return success_response(
        await request.app.state.asset_service.create_asset(library_id, payload)
    )


@asset_router.delete(
    "/api/asset-libraries/{library_id}/assets/{asset_id}", status_code=204
)
async def delete_asset(library_id: str, asset_id: str, request: Request):
    await request.app.state.asset_service.delete_asset(library_id, asset_id)
