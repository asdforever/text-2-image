from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from ..application.reverse_project_service import ReverseModule, ReverseOverall
from ..core.http import success_response


reverse_project_router = APIRouter()


class ReverseProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=200)


class ReverseProjectPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expectedRevision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=500)
    summary: str | None = Field(default=None, max_length=10000)
    suitableFor: str | None = Field(default=None, max_length=10000)
    goal: str | None = Field(default=None, max_length=10000)
    requiredMaterials: str | None = Field(default=None, max_length=10000)
    notSuitableFor: str | None = Field(default=None, max_length=10000)
    overall: ReverseOverall | None = None
    modules: list[ReverseModule] | None = Field(default=None, max_length=64)


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)


class ReferenceOrderInput(RevisionInput):
    referenceIds: list[UUID] = Field(max_length=16)


class ReverseBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    target: Literal["hero", "suite"]
    scope: Literal["overall", "module"]
    versionId: UUID
    targetModuleId: str | None = Field(default=None, min_length=1, max_length=200)
    sourceModuleId: str | None = Field(default=None, min_length=1, max_length=200)


def _reference_view(project_id: UUID, item) -> dict:
    return {
        "id": str(item.id),
        "ordinal": item.ordinal,
        "filename": item.filename,
        "width": item.width,
        "height": item.height,
        "mimeType": item.mime_type,
        "previewUrl": f"/api/reverse-projects/{project_id}/references/{item.id}/preview",
    }


def _version_summary(item) -> dict:
    return {
        "id": str(item.id),
        "versionNo": item.version_no,
        "createdAt": item.created_at.isoformat(),
        "revision": item.revision,
    }


def reverse_project_view(project) -> dict:
    analysis = {"status": project.analysis_status}
    if project.analysis_error:
        analysis["error"] = project.analysis_error
    return {
        "id": str(project.id),
        "name": project.name,
        "category": project.category,
        "summary": project.summary,
        "suitableFor": project.suitable_for,
        "goal": project.goal,
        "requiredMaterials": project.required_materials,
        "notSuitableFor": project.not_suitable_for,
        "references": [_reference_view(project.id, item) for item in project.references],
        "overall": dict(project.overall),
        "modules": list(project.modules),
        "analysis": analysis,
        "versions": [_version_summary(item) for item in project.versions],
        "latestVersionId": str(project.latest_version_id) if project.latest_version_id else None,
        "revision": project.revision,
        "createdAt": project.created_at.isoformat(),
        "updatedAt": project.updated_at.isoformat(),
    }


def _public_document(document: dict) -> dict:
    result = dict(document)
    result["references"] = [
        {key: value for key, value in item.items() if key != "storageKey"}
        for item in document["references"]
    ]
    return result


def reverse_version_view(version) -> dict:
    return {
        "id": str(version.id),
        "reverseProjectId": str(version.reverse_project_id),
        "versionNo": version.version_no,
        "createdAt": version.created_at.isoformat(),
        "revision": version.revision,
        "document": _public_document(version.document),
    }


def reverse_binding_view(binding) -> dict:
    return {
        "id": str(binding.id),
        "projectId": str(binding.project_id),
        "projectName": binding.project_name,
        "target": binding.target,
        "scope": binding.scope,
        "targetModuleId": binding.target_module_id,
        "reverseProjectId": str(binding.reverse_project_id),
        "reverseProjectName": binding.reverse_project_name,
        "versionId": str(binding.version_id),
        "versionNo": binding.version_no,
        "sourceModuleId": binding.source_module_id,
        "sourceModuleTitle": binding.source_module_title,
        "createdAt": binding.created_at.isoformat(),
    }


@reverse_project_router.post("/api/reverse-projects", status_code=201)
async def create_reverse_project(payload: ReverseProjectCreate, request: Request):
    project = await request.app.state.reverse_project_service.create_project(
        payload.name, payload.category
    )
    return success_response(reverse_project_view(project))


@reverse_project_router.get("/api/reverse-projects")
async def list_reverse_projects(request: Request):
    projects = await request.app.state.reverse_project_service.list_projects()
    return success_response([reverse_project_view(project) for project in projects])


@reverse_project_router.get("/api/reverse-projects/{project_id}")
async def get_reverse_project(project_id: UUID, request: Request):
    project = await request.app.state.reverse_project_service.get_project(project_id)
    return success_response(reverse_project_view(project))


@reverse_project_router.patch("/api/reverse-projects/{project_id}")
async def update_reverse_project(
    project_id: UUID, payload: ReverseProjectPatch, request: Request
):
    changes = payload.model_dump(exclude={"expectedRevision"}, exclude_unset=True)
    project = await request.app.state.reverse_project_service.update_project(
        project_id, payload.expectedRevision, changes
    )
    return success_response(reverse_project_view(project))


@reverse_project_router.post("/api/reverse-projects/{project_id}/references")
async def upload_reverse_reference(
    project_id: UUID, request: Request, file: UploadFile = File(...)
):
    project = await request.app.state.reverse_project_service.add_reference(
        project_id, file.filename or "reference", file.content_type, await file.read()
    )
    return success_response(reverse_project_view(project))


@reverse_project_router.delete(
    "/api/reverse-projects/{project_id}/references/{reference_id}"
)
async def delete_reverse_reference(
    project_id: UUID, reference_id: UUID, request: Request
):
    project = await request.app.state.reverse_project_service.remove_reference(
        project_id, reference_id
    )
    return success_response(reverse_project_view(project))


@reverse_project_router.put("/api/reverse-projects/{project_id}/reference-order")
async def reorder_reverse_references(
    project_id: UUID, payload: ReferenceOrderInput, request: Request
):
    project = await request.app.state.reverse_project_service.reorder_references(
        project_id, payload.expectedRevision, payload.referenceIds
    )
    return success_response(reverse_project_view(project))


@reverse_project_router.get(
    "/api/reverse-projects/{project_id}/references/{reference_id}/preview"
)
async def preview_reverse_reference(
    project_id: UUID, reference_id: UUID, request: Request
):
    stored = await request.app.state.reverse_project_service.preview_reference(
        project_id, reference_id
    )
    return Response(content=stored.data, media_type=stored.content_type)


@reverse_project_router.post("/api/reverse-projects/{project_id}/analyze")
async def analyze_reverse_project(
    project_id: UUID, payload: RevisionInput, request: Request
):
    project = await request.app.state.reverse_project_service.analyze(
        project_id, payload.expectedRevision
    )
    return success_response(reverse_project_view(project))


@reverse_project_router.post(
    "/api/reverse-projects/{project_id}/versions", status_code=201
)
async def publish_reverse_project(
    project_id: UUID, payload: RevisionInput, request: Request
):
    version = await request.app.state.reverse_project_service.publish(
        project_id, payload.expectedRevision
    )
    return success_response(reverse_version_view(version))


@reverse_project_router.get(
    "/api/reverse-projects/{project_id}/versions/{version_id}"
)
async def get_reverse_version(project_id: UUID, version_id: UUID, request: Request):
    version = await request.app.state.reverse_project_service.get_project_version(
        project_id, version_id
    )
    return success_response(reverse_version_view(version))


@reverse_project_router.get("/api/reverse-projects/{project_id}/bindings")
async def list_reverse_project_bindings(project_id: UUID, request: Request):
    bindings = await request.app.state.reverse_project_service.list_reverse_bindings(
        project_id
    )
    return success_response([reverse_binding_view(item) for item in bindings])


@reverse_project_router.get("/api/projects/{project_id}/reverse-bindings")
async def list_project_reverse_bindings(
    project_id: UUID, request: Request, target: Literal["hero", "suite"] | None = None
):
    bindings = await request.app.state.reverse_project_service.list_project_bindings(
        project_id, target
    )
    return success_response([reverse_binding_view(item) for item in bindings])


@reverse_project_router.put("/api/projects/{project_id}/reverse-bindings")
async def put_project_reverse_binding(
    project_id: UUID, payload: ReverseBindingInput, request: Request
):
    binding = await request.app.state.reverse_project_service.put_binding(
        project_id,
        target=payload.target,
        scope=payload.scope,
        version_id=payload.versionId,
        target_module_id=payload.targetModuleId,
        source_module_id=payload.sourceModuleId,
    )
    return success_response(reverse_binding_view(binding))


@reverse_project_router.delete(
    "/api/projects/{project_id}/reverse-bindings/{binding_id}"
)
async def delete_project_reverse_binding(
    project_id: UUID, binding_id: UUID, request: Request
):
    deleted = await request.app.state.reverse_project_service.delete_binding(
        project_id, binding_id
    )
    return success_response(deleted)
