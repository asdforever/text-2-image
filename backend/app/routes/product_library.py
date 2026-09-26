from typing import Any
from uuid import UUID
from fastapi import APIRouter, Request, Header
from fastapi.responses import RedirectResponse
from ..core.http import success_response
from ..core.errors import AppError

router = APIRouter()
def svc(r): return r.app.state.product_library_service
def lib_view(x): return {"id": str(x.id), "name": x.name, "description": x.description, "archivedAt": x.archived_at.isoformat() if x.archived_at else None}
def version_view(v): return {"id": str(v.id), "productType": v.product_type, "sourceSnapshot": v.source_snapshot, "previewUrl": f"/api/products/{v.product_id}/versions/{v.id}/preview" if v.preview_url else None, "status": v.status}


async def product_view(x, request: Request):
    versions = [version_view(v) for v in x.versions]
    assets = []
    project_repository = request.app.state.project_repository
    workspace_id = request.app.state.identity_provider.get_context().workspace_id
    for link in await svc(request).list_product_asset_links(x.id):
        asset = await project_repository.get_asset(link.project_asset_id, workspace_id)
        if asset is None or asset.state != "available":
            continue
        stored = await project_repository.get_object(asset.object_id, workspace_id)
        if stored is None or stored.state != "available":
            continue
        matching_versions = [
            item for item in versions
            if str(item["sourceSnapshot"].get("assetId", "")) == str(asset.id)
        ]
        assets.append(
            {
                "id": str(asset.id),
                "kind": asset.kind,
                "sourceKind": asset.source_kind,
                "originalFilename": stored.original_filename,
                "mimeType": stored.media_type,
                "fileSize": stored.byte_size,
                "width": stored.width,
                "height": stored.height,
                "previewUrl": f"/api/projects/{asset.project_id}/assets/{asset.id}/preview",
                "sourceSnapshot": asset.source_snapshot,
                "versions": matching_versions,
            }
        )
    return {
        "id": str(x.id),
        "libraryId": str(x.library_id),
        "name": x.name,
        "projectId": str(x.project_id) if x.project_id else None,
        "archivedAt": x.archived_at.isoformat() if x.archived_at else None,
        "versions": versions,
        "assets": assets,
    }

@router.post("/api/product-libraries", status_code=201)
async def create_library(payload: dict[str, Any], request: Request): return success_response(lib_view(await svc(request).create_library(str(payload.get("name", "")), str(payload.get("description", "")))))
@router.get("/api/product-libraries")
async def list_libraries(request: Request, includeArchived: bool = False): return success_response([lib_view(x) for x in await svc(request).list_libraries(includeArchived)])
@router.get("/api/product-libraries/{library_id}")
async def get_library(library_id: UUID, request: Request): return success_response(lib_view(await svc(request).get_library(library_id)))
@router.post("/api/product-libraries/{library_id}/archive")
async def archive_library(library_id: UUID, request: Request): return success_response(lib_view(await svc(request).archive_library(library_id)))
@router.post("/api/product-libraries/{library_id}/products", status_code=201)
async def create_product(library_id: UUID, payload: dict[str, Any], request: Request): return success_response(await product_view(await svc(request).create_product(library_id, str(payload.get("name", "")), UUID(str(payload["projectId"])) if payload.get("projectId") else None), request))
@router.get("/api/product-libraries/{library_id}/products")
async def list_products(library_id: UUID, request: Request, includeArchived: bool = False): return success_response([await product_view(x, request) for x in await svc(request).list_products(library_id, includeArchived)])
@router.get("/api/products/{product_id}")
async def get_product(product_id: UUID, request: Request): return success_response(await product_view(await svc(request).get_product(product_id), request))
@router.get("/api/products/{product_id}/versions")
async def list_versions(product_id: UUID, request: Request, productType: str | None = None, status: str | None = None):
    return success_response([version_view(v) for v in await svc(request).list_versions(product_id, productType, status)])
@router.post("/api/products/{product_id}/versions/{version_id}/archive")
async def archive_version(product_id: UUID, version_id: UUID, request: Request):
    v = await svc(request).archive_version(product_id, version_id); return success_response({"id": str(v.id), "status": v.status})
@router.post("/api/products/{product_id}/archive")
async def archive_product(product_id: UUID, request: Request): return success_response(await product_view(await svc(request).archive_product(product_id), request))
@router.post("/api/product-libraries/{library_id}/products/{product_id}/versions/publish", status_code=201)
async def publish(library_id: UUID, product_id: UUID, payload: dict[str, Any], request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    version = await svc(request).publish_version(library_id, product_id, dict(payload.get("sourceVersion") or {}), product_type=str(payload.get("productType", "hero")), idempotency_key=idempotency_key)
    return success_response({**version_view(version), "productId": str(version.product_id)})

@router.get("/api/products/{product_id}/versions/{version_id}/preview")
async def preview(product_id: UUID, version_id: UUID, request: Request):
    version = await svc(request).get_version(product_id, version_id)
    # 只允许跳转到发布时固化的站内预览地址，避免暴露对象存储地址。
    if not version.preview_url or not version.preview_url.startswith("/"):
        raise AppError("PRODUCT_PREVIEW_NOT_AVAILABLE", "正式产品版本暂无受控预览", 404)
    return RedirectResponse(version.preview_url, status_code=307, headers={"cache-control": "private, max-age=60"})
