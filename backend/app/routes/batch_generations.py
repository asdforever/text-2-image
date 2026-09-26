from uuid import UUID

from fastapi import APIRouter, Header, Request

from ..application.batch_generation_service import (
    BatchHeroModuleInput,
    BatchHeroPromptCompilationInput,
)
from ..core.errors import AppError
from ..core.http import success_response
from ..schemas import BatchGenerationConfirmInput, BatchHeroPromptCompileInput


batch_generation_router = APIRouter(prefix="/api/projects/{project_id}/generation-batches")


def _batch_view(batch) -> dict:
    return {
        "id": str(batch.id), "projectId": str(batch.project_id),
        "sourceAssetId": str(batch.source_asset_id), "status": batch.status,
        "plannerVersion": batch.snapshot.get("plannerVersion", "v2"),
        "kind": getattr(batch, "kind", "hero"), "sourcePlanId": str(getattr(batch, "source_plan_id", None)) if getattr(batch, "source_plan_id", None) else None,
        "createdAt": batch.created_at.isoformat(), "updatedAt": batch.updated_at.isoformat(),
        "confirmedAt": batch.confirmed_at.isoformat() if batch.confirmed_at else None,
        "completedAt": batch.completed_at.isoformat() if batch.completed_at else None,
        "error": ({"code": batch.error_code, "message": batch.error_message}
                  if getattr(batch, "error_code", None) else None),
    }


def _task_identity(task) -> dict:
    snapshot = task.snapshot
    prompt = snapshot.get("promptSnapshot", snapshot)
    module = prompt.get("module") or prompt.get("selection", {}).get("module", {})
    return {"taskId": task.module_key,
            "moduleId": snapshot.get("moduleId") or prompt.get("moduleId") or module.get("id", task.module_key),
            "moduleLabel": snapshot.get("title") or module.get("label", task.module_key)}


def _detail_view(detail, project_id: UUID) -> dict:
    identities = {task.id: _task_identity(task) for task in detail.module_tasks}
    return {
        **_batch_view(detail.batch),
        "modules": [
            {
                "id": str(task.id), "moduleKey": task.module_key, "position": getattr(task, "position", None),
                **identities[task.id],
                "resultCount": task.requested_image_count,
                "constraints": task.snapshot.get("constraints", {}),
                "compiledTaskPrompt": task.compiled_task_prompt,
                "visibleFacts": (task.compiler_output or {}).get("visibleFacts", []),
                "unconfirmedItems": (task.compiler_output or {}).get("unconfirmedItems", []),
                "confirmedTaskPrompt": task.confirmed_task_prompt,
                "finalPromptSha256": task.final_prompt_sha256,
            }
            for task in detail.module_tasks
        ],
        "slots": [
            {
                "id": str(slot.id), "moduleTaskId": str(slot.module_task_id),
                "moduleKey": slot.module_key, "ordinal": slot.ordinal, "status": slot.status,
                **identities.get(slot.module_task_id, {}),
                "generatedAssetId": str(slot.generated_asset_id) if slot.generated_asset_id else None,
                "generatedAssetPreviewUrl": (
                    f"/api/projects/{project_id}/assets/{slot.generated_asset_id}/preview"
                    if slot.generated_asset_id else None
                ),
                "error": ({"code": slot.error_code, "message": slot.error_message}
                          if slot.error_code else None),
            }
            for slot in detail.slots
        ],
        "progress": {
            "total": detail.progress.total, "queued": detail.progress.queued,
            "leased": detail.progress.leased, "dispatching": detail.progress.dispatching,
            "succeeded": detail.progress.succeeded, "failed": detail.progress.failed,
            "cancelled": detail.progress.cancelled, "needsRetry": detail.progress.needs_retry,
            "completed": detail.progress.completed,
        },
    }


async def _detail_for_project(request: Request, project_id: UUID, batch_id: UUID):
    workspace_id = request.app.state.identity_provider.get_context().workspace_id
    detail = await request.app.state.batch_generation_repository.get_batch_detail(batch_id, workspace_id)
    if detail is None or detail.batch.project_id != project_id:
        raise AppError("BATCH_GENERATION_NOT_FOUND", "批次生成任务不存在", 404)
    return detail


@batch_generation_router.post("/compile", status_code=201)
async def compile_batch(project_id: UUID, payload: BatchHeroPromptCompileInput, request: Request,
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    batch = await request.app.state.batch_generation_service.compile_prompt_batch(
        project_id,
        BatchHeroPromptCompilationInput(
            source_asset_id=payload.sourceAssetId, market_id=payload.marketId, model_id=payload.modelId,
            style_id=payload.styleId, aspect_ratio=payload.aspectRatio, resolution=payload.resolution,
            output_language=payload.outputLanguage, custom_style=payload.customStyle,
            module_plan_id=payload.modulePlanId,
            reverse_version_id=payload.reverseVersionId,
            modules=[BatchHeroModuleInput(item.moduleId, item.resultCount, [
                parameter.model_dump() for parameter in item.moduleParameters
            ], task_id=item.taskId, reverse_reference=(
                item.reverseReference.model_dump(mode="python")
                if item.reverseReference else None
            )) for item in payload.modules],
        ),
        idempotency_key or "",
    )
    return success_response(_batch_view(batch))


@batch_generation_router.get("/by-request")
async def recover_batch(project_id: UUID, key: str, request: Request):
    workspace_id = request.app.state.identity_provider.get_context().workspace_id
    batch = await request.app.state.batch_generation_repository.get_by_compile_idempotency(workspace_id, key)
    if batch is None:
        return success_response(None)
    if batch.project_id != project_id:
        raise AppError("BATCH_GENERATION_NOT_FOUND", "批次生成任务不存在", 404)
    return success_response(_detail_view(await _detail_for_project(request, project_id, batch.id), project_id))


@batch_generation_router.get("/{batch_id}")
async def get_batch(project_id: UUID, batch_id: UUID, request: Request):
    return success_response(_detail_view(await _detail_for_project(request, project_id, batch_id), project_id))


@batch_generation_router.post("/{batch_id}/confirm")
async def confirm_batch(project_id: UUID, batch_id: UUID, payload: BatchGenerationConfirmInput, request: Request,
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    batch = await request.app.state.batch_generation_confirmation_service.confirm_batch(
        project_id, batch_id, payload.moduleTaskPrompts, idempotency_key or ""
    )
    detail = await _detail_for_project(request, project_id, batch.id)
    return success_response(_detail_view(detail, project_id))


@batch_generation_router.post("/{batch_id}/cancel")
async def cancel_batch(project_id: UUID, batch_id: UUID, request: Request):
    await _detail_for_project(request, project_id, batch_id)
    workspace_id = request.app.state.identity_provider.get_context().workspace_id
    await request.app.state.batch_generation_repository.cancel_batch(batch_id, workspace_id)
    detail = await _detail_for_project(request, project_id, batch_id)
    return success_response(_detail_view(detail, project_id))


@batch_generation_router.post("/{batch_id}/slots/{slot_id}/retry")
async def retry_slot(project_id: UUID, batch_id: UUID, slot_id: UUID, request: Request):
    await _detail_for_project(request, project_id, batch_id)
    workspace_id = request.app.state.identity_provider.get_context().workspace_id
    slot = await request.app.state.batch_generation_repository.retry_slot(slot_id, workspace_id)
    if slot.batch_id != batch_id:
        raise AppError("GENERATION_SLOT_NOT_FOUND", "图片槽位不存在", 404)
    detail = await _detail_for_project(request, project_id, batch_id)
    return success_response({"slot": next(item for item in _detail_view(detail, project_id)["slots"] if item["id"] == str(slot_id))})
