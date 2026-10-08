from uuid import UUID
import json

from fastapi import APIRouter, Header, Request, Response

from ..core.errors import AppError
from ..core.http import success_response
from ..schemas import ProjectAssetSelectionInput, ProjectCreate


project_router = APIRouter()


def _project_view(project) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "status": project.status,
        "archivedAt": project.archived_at.isoformat() if project.archived_at else None,
        "createdAt": project.created_at.isoformat(),
        "updatedAt": project.updated_at.isoformat(),
    }


def _asset_view(asset, object_record) -> dict:
    return {
        "id": str(asset.id),
        "kind": asset.kind,
        "sourceAssetId": str(asset.source_asset_id) if asset.source_asset_id else None,
        "generationSnapshotId": str(asset.generation_snapshot_id)
        if asset.generation_snapshot_id
        else None,
        "sourceKind": asset.source_kind,
        "sourceLibraryId": asset.source_library_id,
        "sourceResourceId": asset.source_resource_id,
        "sourceResourceVersionId": asset.source_resource_version_id,
        "sourceSnapshot": asset.source_snapshot,
        "state": asset.state,
        "filename": object_record.original_filename,
        "mimeType": object_record.media_type,
        "byteSize": object_record.byte_size,
        "width": object_record.width,
        "height": object_record.height,
        "sha256": object_record.sha256,
        "createdAt": asset.created_at.isoformat(),
    }


async def _project_detail_view(request: Request, project) -> dict:
    asset_service = request.app.state.project_asset_service
    details = await asset_service.list_asset_details(project.id)
    data = _project_view(project)
    data["assets"] = [_asset_view(asset, obj) for asset, obj in details]
    data["selections"] = {
        role: str(asset_id)
        for role, asset_id in (await asset_service.get_selections(project.id)).items()
    }
    return data


@project_router.post("/api/projects", status_code=201)
async def create_project(
    payload: ProjectCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    project = await request.app.state.project_service.create_project(
        payload.name, idempotency_key
    )
    return success_response(_project_view(project))


@project_router.get("/api/projects")
async def list_projects(includeArchived: bool = False, request: Request = None):
    summaries = await request.app.state.project_service.list_project_summaries(
        include_archived=includeArchived
    )
    return success_response([
        {**_project_view(summary.project), "assetCount": summary.asset_count,
         "coverAssetId": str(summary.cover_asset_id) if summary.cover_asset_id else None}
        for summary in summaries
    ])


@project_router.get("/api/projects/{project_id}")
async def get_project(project_id: UUID, request: Request):
    project = await request.app.state.project_service.get_project(project_id)
    if project is None:
        raise AppError("INVALID_PROJECT_ID", "project does not exist", 404)
    return success_response(await _project_detail_view(request, project))


@project_router.post("/api/projects/{project_id}/archive")
async def archive_project(
    project_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    project = await request.app.state.project_service.archive_project(
        project_id, idempotency_key
    )
    if project is None:
        raise AppError("INVALID_PROJECT_ID", "project does not exist", 404)
    return success_response(_project_view(project))


@project_router.get("/api/projects/{project_id}/assets")
async def list_project_assets(project_id: UUID, request: Request):
    details = await request.app.state.project_asset_service.list_asset_details(project_id)
    return success_response([_asset_view(asset, obj) for asset, obj in details])


@project_router.post("/api/projects/{project_id}/assets", status_code=201)
async def upload_project_asset(
    project_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    form = await request.form()
    file = form.get("file")
    upload = file if hasattr(file, "read") and hasattr(file, "filename") else None
    if upload is None:
        raise AppError("INVALID_PROJECT_ASSET_UPLOAD", "image file is required", 400)
    source_asset_id = None
    if form.get("sourceAssetId"):
        try:
            source_asset_id = UUID(str(form.get("sourceAssetId")))
        except ValueError as exc:
            raise AppError("INVALID_SOURCE_ASSET", "source asset id is invalid", 400) from exc
    source_snapshot: dict = {}
    if form.get("sourceSnapshot"):
        try:
            source_snapshot = json.loads(str(form.get("sourceSnapshot")))
        except json.JSONDecodeError as exc:
            raise AppError("INVALID_SOURCE_SNAPSHOT", "source snapshot is invalid", 400) from exc
    asset = await request.app.state.project_asset_service.upload_asset(
        project_id,
        str(form.get("kind") or ""),
        await upload.read(),
        upload.content_type,
        upload.filename or "upload",
        source_asset_id=source_asset_id,
        idempotency_key=idempotency_key,
        source_kind=str(form.get("sourceKind") or "upload"),
        source_library_id=str(form.get("sourceLibraryId")) if form.get("sourceLibraryId") else None,
        source_resource_id=str(form.get("sourceResourceId")) if form.get("sourceResourceId") else None,
        source_resource_version_id=str(form.get("sourceResourceVersionId")) if form.get("sourceResourceVersionId") else None,
        source_snapshot=source_snapshot,
    )
    _, object_record = await request.app.state.project_asset_service.get_asset_details(
        project_id, asset.id
    )
    return success_response(_asset_view(asset, object_record))


@project_router.get("/api/projects/{project_id}/assets/{asset_id}/preview")
async def preview_project_asset(project_id: UUID, asset_id: UUID, request: Request):
    stored = await request.app.state.project_asset_service.get_preview(project_id, asset_id)
    return Response(content=stored.data, media_type=stored.content_type)


@project_router.put("/api/projects/{project_id}/selections/{role}")
async def select_project_asset(
    project_id: UUID,
    role: str,
    payload: ProjectAssetSelectionInput,
    request: Request,
):
    asset = await request.app.state.project_asset_service.select_asset(
        project_id, role, payload.assetId
    )
    _, object_record = await request.app.state.project_asset_service.get_asset_details(
        project_id, asset.id
    )
    return success_response(_asset_view(asset, object_record))


@project_router.delete("/api/projects/{project_id}/selections/{role}", status_code=204)
async def clear_project_asset_selection(project_id: UUID, role: str, request: Request):
    cleared = await request.app.state.project_asset_service.clear_selection(project_id, role)
    if not cleared:
        raise AppError("PROJECT_ASSET_SELECTION_NOT_FOUND", "project asset selection does not exist", 404)
    return Response(status_code=204)


@project_router.delete("/api/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    deleted = await request.app.state.project_service.delete_project(
        project_id, idempotency_key
    )
    if not deleted:
        raise AppError("INVALID_PROJECT_ID", "project does not exist", 404)
    return Response(status_code=204)


@project_router.post("/api/projects/{project_id}/assets/{asset_id}/cleanup")
async def retry_project_asset_cleanup(project_id: UUID, asset_id: UUID, request: Request):
    cleaned = await request.app.state.project_asset_service.retry_asset_cleanup(
        project_id, asset_id
    )
    return success_response({"cleaned": cleaned})


@project_router.delete("/api/projects/{project_id}/assets/{asset_id}", status_code=204)
async def delete_project_asset(project_id: UUID, asset_id: UUID, request: Request):
    await request.app.state.project_asset_service.delete_asset(project_id, asset_id)
    return Response(status_code=204)
