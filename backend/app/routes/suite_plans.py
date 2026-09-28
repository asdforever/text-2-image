from uuid import UUID

from fastapi import APIRouter, Header, Request

from ..application.suite_planning_ports import PlanningReferenceRequest
from ..application.suite_planning_service import (
    SuitePlanCompilationInput,
    SuitePlanModuleInput,
    SuitePlanModuleUpdateInput,
)
from ..core.http import success_response
from ..core.errors import AppError
from ..schemas import (
    SuitePlanCompileInput,
    SuitePlanConfirmInput,
    SuitePlanModulePatchInput,
    SuitePlanOrderPatchInput,
)


suite_plan_router = APIRouter(prefix="/api/projects/{project_id}/suite-plans")


def _plan_view(detail) -> dict:
    plan = detail.plan
    return {
        "id": str(plan.id),
        "projectId": str(plan.project_id),
        "status": plan.status,
        "plannerVersion": plan.snapshot.get("plannerVersion", "v2"),
        "revision": plan.revision,
        "snapshot": plan.snapshot,
        "sourceAssets": plan.snapshot.get("sourceAssets", []),
        "constraints": plan.snapshot.get("constraints", {}),
        "references": plan.snapshot.get("references", []),
        "generationBatchId": (
            str(plan.generation_batch_id) if plan.generation_batch_id else None
        ),
        "modules": [
            {
                "id": str(module.id),
                "moduleKey": module.module_key,
                "taskId": module.module_key,
                "moduleId": module.prompt_snapshot.get("moduleId") or module.prompt_snapshot.get("module", {}).get("id", module.module_key),
                "moduleLabel": module.prompt_snapshot.get("module", {}).get("label", module.title),
                "position": module.position,
                "resultCount": module.requested_image_count,
                "revision": module.revision,
                "title": module.title,
                "copySummary": module.copy_summary,
                "visualDirection": module.visual_direction,
                "moduleParameters": module.module_parameters,
                "promptSnapshot": module.prompt_snapshot,
                "compiledTaskPrompt": module.compiled_task_prompt,
                "currentTaskPrompt": module.current_task_prompt,
                "visibleFacts": (module.compiler_output or {}).get("visibleFacts", []),
                "unconfirmedItems": (module.compiler_output or {}).get(
                    "unconfirmedItems", []
                ),
            }
            for module in detail.modules
        ],
        "error": (
            {"code": plan.error_code, "message": plan.error_message}
            if plan.error_code else None
        ),
        "createdAt": plan.created_at.isoformat(),
        "updatedAt": plan.updated_at.isoformat(),
        "confirmedAt": plan.confirmed_at.isoformat() if plan.confirmed_at else None,
    }


@suite_plan_router.post("/compile", status_code=201)
async def compile_suite_plan(
    project_id: UUID,
    payload: SuitePlanCompileInput,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    plan = await request.app.state.suite_planning_service.compile_plan(
        project_id,
        SuitePlanCompilationInput(
            source_asset_ids=payload.sourceAssetIds,
            market_id=payload.marketId,
            model_id=payload.modelId,
            style_id=payload.styleId,
            aspect_ratio=payload.aspectRatio,
            resolution=payload.resolution,
            output_language=payload.outputLanguage,
            modules=[
                SuitePlanModuleInput(
                    item.moduleId,
                    item.resultCount,
                    [parameter.model_dump() for parameter in item.moduleParameters],
                    task_id=item.taskId,
                    task_design=item.taskDesign.model_dump(exclude_none=True) if item.taskDesign else None,
                    reverse_reference=(
                        item.reverseReference.model_dump(mode="python")
                        if item.reverseReference else None
                    ),
                )
                for item in payload.modules
            ],
            user_notes=payload.userNotes,
            module_plan_id=payload.modulePlanId,
            reverse_version_id=payload.reverseVersionId,
            custom_style=payload.customStyle,
            references=[
                PlanningReferenceRequest(item.referenceId, item.version)
                for item in payload.references
            ],
        ),
        idempotency_key or "",
    )
    detail = await request.app.state.suite_planning_service.get_plan(project_id, plan.id)
    return success_response(_plan_view(detail))


@suite_plan_router.get("/latest")
async def get_latest_suite_plan(project_id: UUID, request: Request):
    detail = await request.app.state.suite_planning_service.get_latest_plan(project_id)
    return success_response(_plan_view(detail))


@suite_plan_router.get("/by-request")
async def recover_suite_plan(project_id: UUID, key: str, request: Request):
    workspace_id = request.app.state.identity_provider.get_context().workspace_id
    repository = request.app.state.suite_planning_repository
    plan = await repository.get_by_compile_idempotency(workspace_id, key)
    if plan is None:
        return success_response(None)
    if plan.project_id != project_id:
        raise AppError("SUITE_PLAN_NOT_FOUND", "套图规划不存在", 404)
    detail = await repository.get_plan_detail(plan.id, workspace_id, project_id)
    if detail is None:
        raise AppError("SUITE_PLAN_NOT_FOUND", "套图规划不存在", 404)
    return success_response(_plan_view(detail))


@suite_plan_router.get("/{plan_id}")
async def get_suite_plan(project_id: UUID, plan_id: UUID, request: Request):
    detail = await request.app.state.suite_planning_service.get_plan(project_id, plan_id)
    return success_response(_plan_view(detail))


@suite_plan_router.patch("/{plan_id}/modules/{module_id}")
async def update_suite_plan_module(
    project_id: UUID,
    plan_id: UUID,
    module_id: UUID,
    payload: SuitePlanModulePatchInput,
    request: Request,
):
    detail = await request.app.state.suite_planning_service.update_module(
        project_id,
        plan_id,
        SuitePlanModuleUpdateInput(
            module_id=module_id,
            expected_plan_revision=payload.expectedPlanRevision,
            expected_module_revision=payload.expectedModuleRevision,
            title=payload.title,
            copy_summary=payload.copySummary,
            visual_direction=payload.visualDirection,
            current_task_prompt=payload.currentTaskPrompt,
            requested_image_count=payload.resultCount,
            module_parameters=(
                [item.model_dump() for item in payload.moduleParameters]
                if payload.moduleParameters is not None else None
            ),
        ),
    )
    return success_response(_plan_view(detail))


@suite_plan_router.patch("/{plan_id}/order")
async def reorder_suite_plan_modules(
    project_id: UUID,
    plan_id: UUID,
    payload: SuitePlanOrderPatchInput,
    request: Request,
):
    detail = await request.app.state.suite_planning_service.reorder_modules(
        project_id,
        plan_id,
        payload.moduleIds,
        expected_plan_revision=payload.expectedPlanRevision,
    )
    return success_response(_plan_view(detail))


@suite_plan_router.post("/{plan_id}/confirm")
async def confirm_suite_plan(
    project_id: UUID,
    plan_id: UUID,
    payload: SuitePlanConfirmInput,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    batch = await request.app.state.suite_planning_confirmation_service.confirm_plan(
        project_id,
        plan_id,
        expected_plan_revision=payload.expectedPlanRevision,
        module_task_prompts=payload.moduleTaskPrompts,
        idempotency_key=idempotency_key or "",
    )
    detail = await request.app.state.suite_planning_service.get_plan(project_id, plan_id)
    return success_response({**_plan_view(detail), "batchId": str(batch.id)})
