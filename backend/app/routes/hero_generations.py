from uuid import UUID

from fastapi import APIRouter, Header, Request

from ..application.hero_generation_service import HeroPromptCompilationInput
from ..core.http import success_response
from ..schemas import HeroGenerationConfirmInput, HeroPromptCompileInput


hero_generation_router = APIRouter(
    prefix="/api/projects/{project_id}/hero-generations"
)


def _task_view(task, project_id: UUID) -> dict:
    compiler_output = task.compiler_output or {}
    generated_asset_id = (
        str(task.generated_asset_id) if task.generated_asset_id is not None else None
    )
    return {
        "id": str(task.id),
        "projectId": str(task.project_id),
        "sourceAssetId": str(task.source_asset_id),
        "status": task.status,
        "plannerVersion": task.snapshot.get("plannerVersion", "v2"),
        "snapshot": task.snapshot,
        "constraints": task.snapshot.get("constraints", {}),
        "compiledTaskPrompt": task.compiled_task_prompt,
        "visibleFacts": compiler_output.get("visibleFacts", []),
        "unconfirmedItems": compiler_output.get("unconfirmedItems", []),
        "confirmedTaskPrompt": task.confirmed_task_prompt,
        "finalPrompt": task.final_prompt,
        "finalPromptSha256": task.final_prompt_sha256,
        "providerRequest": task.provider_request,
        "generatedAssetId": generated_asset_id,
        "generatedAssetPreviewUrl": (
            f"/api/projects/{project_id}/assets/{generated_asset_id}/preview"
            if generated_asset_id is not None
            else None
        ),
        "error": (
            {"code": task.error_code, "message": task.error_message}
            if task.error_code is not None
            else None
        ),
        "createdAt": task.created_at.isoformat(),
        "updatedAt": task.updated_at.isoformat(),
        "confirmedAt": task.confirmed_at.isoformat() if task.confirmed_at else None,
        "completedAt": task.completed_at.isoformat() if task.completed_at else None,
    }


@hero_generation_router.post("/compile", status_code=201)
async def compile_hero_prompt(
    project_id: UUID,
    payload: HeroPromptCompileInput,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    task = await request.app.state.hero_generation_service.compile_prompt(
        project_id,
        HeroPromptCompilationInput(
            source_asset_id=payload.sourceAssetId,
            market_id=payload.marketId,
            model_id=payload.modelId,
            style_id=payload.styleId,
            module_id=payload.moduleId,
            aspect_ratio=payload.aspectRatio,
            resolution=payload.resolution,
            output_language=payload.outputLanguage,
            custom_style=payload.customStyle,
            module_parameters=[item.model_dump() for item in payload.moduleParameters],
            result_count=payload.resultCount,
        ),
        idempotency_key or "",
    )
    return success_response(_task_view(task, project_id))


@hero_generation_router.get("/{task_id}")
async def get_hero_generation(project_id: UUID, task_id: UUID, request: Request):
    task = await request.app.state.hero_generation_service.get_task(project_id, task_id)
    return success_response(_task_view(task, project_id))


@hero_generation_router.post("/{task_id}/confirm")
async def confirm_hero_generation(
    project_id: UUID,
    task_id: UUID,
    payload: HeroGenerationConfirmInput,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    task = await request.app.state.hero_generation_service.confirm_generation(
        project_id,
        task_id,
        task_prompt=payload.taskPrompt,
        idempotency_key=idempotency_key or "",
    )
    return success_response(_task_view(task, project_id))
