from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from ..core.http import success_response


reverse_execution_router = APIRouter()


class ReverseExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versionId: UUID
    sourceAssetId: UUID | None = None
    productFacts: dict[str, Any] = Field(default_factory=dict)
    parameterBrief: str = Field(default="", max_length=20000)
    outputSettings: dict[str, Any] = Field(default_factory=dict)


class ReverseExecutionSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)
    document: dict[str, Any]


class ReverseExecutionCompile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)
    productFacts: dict[str, Any] | None = None


class ReverseExecutionParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)


class ReverseExecutionGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expectedRevision: int = Field(ge=1)
    taskIds: list[str] | None = None
    sourceAssetId: UUID | None = None
    aspectRatio: str = Field(default="1:1", min_length=1, max_length=20)
    resolution: str = Field(default="标准 1K", min_length=1, max_length=50)


def reverse_execution_view(record) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "projectId": str(record.project_id),
        "reverseVersionId": str(record.reverse_version_id),
        "document": record.document,
        "versionId": record.document.get("versionId", str(record.reverse_version_id)),
        "referenceCount": record.document.get("referenceCount", len(record.document.get("tasks", []))),
        "sourceAssetId": record.document.get("sourceAssetId"),
        "productFacts": record.document.get("productFacts", {}),
        "parameterBrief": record.document.get("parameterBrief", ""),
        "parametersAssigned": record.document.get("parametersAssigned", False),
        "parameterSummary": record.document.get("parameterSummary", ""),
        "parameterWarnings": record.document.get("parameterWarnings", []),
        "outputSettings": record.document.get("outputSettings", {}),
        "tasks": record.document.get("tasks", []),
        "revision": record.revision,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }


@reverse_execution_router.get("/api/projects/{project_id}/reverse-execution")
async def get_reverse_execution(project_id: UUID, request: Request):
    record = await request.app.state.reverse_execution_service.get(project_id)
    return success_response(reverse_execution_view(record) if record else None)


@reverse_execution_router.post("/api/projects/{project_id}/reverse-execution", status_code=201)
async def create_reverse_execution(project_id: UUID, payload: ReverseExecutionCreate, request: Request):
    record = await request.app.state.reverse_execution_service.generate(
        project_id,
        payload.versionId,
        source_asset_id=payload.sourceAssetId,
        product_facts=payload.productFacts,
        parameter_brief=payload.parameterBrief,
        output_settings=payload.outputSettings,
    )
    return success_response(reverse_execution_view(record))


@reverse_execution_router.patch("/api/projects/{project_id}/reverse-execution")
async def save_reverse_execution(project_id: UUID, payload: ReverseExecutionSave, request: Request):
    record = await request.app.state.reverse_execution_service.save(
        project_id, payload.expectedRevision, payload.document
    )
    return success_response(reverse_execution_view(record))


@reverse_execution_router.post("/api/projects/{project_id}/reverse-execution/compile")
async def compile_reverse_execution(project_id: UUID, payload: ReverseExecutionCompile, request: Request):
    record = await request.app.state.reverse_execution_service.compile(
        project_id, payload.expectedRevision, payload.productFacts
    )
    return success_response(reverse_execution_view(record))


@reverse_execution_router.post("/api/projects/{project_id}/reverse-execution/parameters")
async def assign_reverse_execution_parameters(project_id: UUID, payload: ReverseExecutionParameters, request: Request):
    record = await request.app.state.reverse_execution_service.assign_parameters(project_id, payload.expectedRevision)
    return success_response(reverse_execution_view(record))


@reverse_execution_router.post("/api/projects/{project_id}/reverse-execution/generate")
async def generate_reverse_execution(project_id: UUID, payload: ReverseExecutionGenerate, request: Request):
    record = await request.app.state.reverse_execution_generation_service.generate(
        project_id,
        payload.expectedRevision,
        task_ids=payload.taskIds,
        source_asset_id=payload.sourceAssetId,
        aspect_ratio=payload.aspectRatio,
        resolution=payload.resolution,
    )
    return success_response(reverse_execution_view(record))
