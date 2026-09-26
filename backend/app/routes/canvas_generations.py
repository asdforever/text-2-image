from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Header, Request
from pydantic import BaseModel, Field
from ..core.http import success_response

canvas_generation_router = APIRouter()


class CanvasGenerationInput(BaseModel):
    stepId: str = Field(min_length=1, max_length=200)
    baseRevisionId: str = Field(min_length=1, max_length=200)
    taskPrompt: str = Field(min_length=1, max_length=30000)
    sourceAssetIds: list[UUID] | None = Field(default=None, max_length=20)
    restoredConstraintsHash: str | None = Field(default=None, min_length=64, max_length=64, pattern="^[a-f0-9]+$")


class CanvasVersionSelection(BaseModel):
    stepId: str = Field(min_length=1, max_length=200)
    outputIndex: int = Field(ge=0)
    assetId: UUID


@canvas_generation_router.post("/api/projects/{project_id}/canvas/generations", status_code=202)
async def regenerate(project_id: UUID, payload: CanvasGenerationInput, request: Request, background: BackgroundTasks, idempotency_key: str = Header(min_length=1, max_length=200, alias="Idempotency-Key")):
    service = request.app.state.canvas_generation_service
    revision = await service.submit(project_id, payload.stepId, payload.baseRevisionId, payload.taskPrompt, [str(id) for id in payload.sourceAssetIds] if payload.sourceAssetIds is not None else None, idempotency_key, payload.restoredConstraintsHash)
    if revision["status"] == "queued":
        background.add_task(service.execute, project_id, payload.stepId, revision["id"])
    return success_response(revision)


@canvas_generation_router.get("/api/projects/{project_id}/canvas/constraint-preview")
async def preview_constraints(project_id: UUID, stepId: str, baseRevisionId: str, request: Request):
    return success_response(await request.app.state.canvas_generation_service.preview_constraints(project_id, stepId, baseRevisionId))


@canvas_generation_router.post("/api/projects/{project_id}/canvas/version-selection")
async def select_version(project_id: UUID, payload: CanvasVersionSelection, request: Request):
    return success_response(await request.app.state.canvas_generation_service.select(project_id, payload.stepId, payload.outputIndex, str(payload.assetId)))
