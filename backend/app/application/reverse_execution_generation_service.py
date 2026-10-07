"""Generate project assets from the project reverse execution plan."""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from ..core.errors import AppError
from ..reverse_execution_repository import ReverseExecutionPlanRecord
from .hero_generation_ports import ImageEditInput, ImageEditRequest
from .reverse_execution import compile_task_prompt


class ReverseExecutionGenerationService:
    """Runs one image edit per reverse task and archives every output."""

    def __init__(
        self,
        *,
        plan_service: Any,
        repository: Any,
        project_repository: Any,
        project_asset_service: Any,
        reverse_project_service: Any,
        image_editor: Any,
        project_archive: Any,
        identity_provider: Any,
        provider_model: str,
        model_connections: Any | None = None,
    ) -> None:
        self.plan_service = plan_service
        self.repository = repository
        self.project_repository = project_repository
        self.project_asset_service = project_asset_service
        self.reverse_project_service = reverse_project_service
        self.image_editor = image_editor
        self.project_archive = project_archive
        self.identity_provider = identity_provider
        self.provider_model = provider_model
        self.model_connections = model_connections

    async def generate(
        self,
        project_id: UUID,
        expected_revision: int,
        *,
        task_ids: Iterable[str] | None = None,
        source_asset_id: UUID | None = None,
        aspect_ratio: str = "1:1",
        resolution: str = "标准 1K",
    ) -> ReverseExecutionPlanRecord:
        plan = await self.plan_service.get(project_id)
        if plan is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        if plan.revision != expected_revision:
            raise AppError("REVERSE_EXECUTION_REVISION_CONFLICT", "项目反推方案已被更新，请重新加载", 409)
        project = await self._require_project(project_id)
        saved_source_id = plan.document.get("sourceAssetId")
        source = await self._resolve_source(project_id, source_asset_id or (UUID(saved_source_id) if saved_source_id else None))
        source_asset, source_object = await self.project_asset_service.get_asset_details(project_id, source.id)
        source_stored = await self.project_asset_service.get_preview(project_id, source.id)
        version = await self.reverse_project_service.get_version(UUID(plan.document["versionId"]))
        references = {str(item["id"]): item for item in version.document.get("references", [])}
        selected = set(task_ids) if task_ids is not None else None
        document = deepcopy(plan.document)
        product_facts = {"商品名称": project.name, **document.get("productFacts", {})}
        document["sourceAssetId"] = str(source.id)
        output_settings = document.get("outputSettings") or {}
        requested_model = output_settings.get("model")
        effective_aspect_ratio = aspect_ratio if aspect_ratio != "1:1" else output_settings.get("aspectRatio", aspect_ratio)
        effective_resolution = resolution if resolution != "标准 1K" else output_settings.get("resolution", resolution)
        model_connection = await self.model_connections.snapshot(requested_model) if self.model_connections is not None else None

        for task in document.get("tasks", []):
            if selected is not None and task.get("id") not in selected:
                continue
            await self._generate_task(
                task,
                references,
                version,
                project,
                source_asset,
                source_object,
                source_stored,
                product_facts,
                effective_aspect_ratio,
                effective_resolution,
                model_connection,
                output_settings,
                plan.id,
            )

        # A single revision is committed for the complete request so the UI can
        # refresh once and still keep optimistic concurrency intact.
        return await self.plan_service.save(project_id, expected_revision, document)

    async def _generate_task(
        self,
        task: dict[str, Any],
        references: dict[str, dict[str, Any]],
        version: Any,
        project: Any,
        source_asset: Any,
        source_object: Any,
        source_stored: Any,
        product_facts: dict[str, Any],
        aspect_ratio: str,
        resolution: str,
        model_connection: dict[str, Any] | None,
        output_settings: dict[str, Any],
        plan_id: UUID,
    ) -> None:
        task["status"] = "generating"
        task.pop("error", None)
        reference_id = str(task.get("referenceImageId"))
        reference = references.get(reference_id)
        try:
            if reference is None:
                raise AppError("REVERSE_REFERENCE_NOT_FOUND", "反推模板图不存在", 404)
            prompt = str(task.get("promptDraft") or compile_task_prompt(task, product_facts, output_settings))
            task["promptDraft"] = prompt
            product_input = ImageEditInput(
                source_stored.data,
                source_object.media_type,
                source_object.original_filename,
            )
            result = await self.image_editor.edit(
                ImageEditRequest(
                    prompt=prompt,
                    image_bytes=source_stored.data,
                    image_mime_type=source_object.media_type,
                    image_filename=source_object.original_filename,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    image_inputs=(product_input,),
                    # The published reverse version supplies the prompt structure;
                    # the reference image itself is intentionally not sent to the
                    # generation model, reducing direct visual imitation.
                    # No task-level connection has been selected in this workbench;
                    # ConfiguredImageEditor therefore resolves the published environment model.
                    model_connection=model_connection,
                )
            )
            generated = await self.project_asset_service.create_generated_asset(
                project.id,
                result.image_bytes,
                result.image_mime_type,
                f"项目反推-{task.get('ordinal', 0)}.png",
                source_asset_id=source_asset.id,
                generation_snapshot_id=plan_id,
                source_kind="reverse_execution",
                source_snapshot={
                    "reverseExecutionPlanId": str(plan_id),
                    "reverseVersionId": str(version.id),
                    "taskId": task.get("id"),
                    "referenceImageId": reference_id,
                    "moduleId": task.get("referenceModuleId"),
                },
            )
            if self.project_archive is not None:
                await self.project_archive.archive_project_output(
                    project_id=project.id,
                    project_name=project.name,
                    product_type="detail",
                    source_version_id=generated.id,
                    preview_url=f"/api/projects/{project.id}/assets/{generated.id}/preview",
                    source_snapshot={
                        "sourceKind": "reverse_execution",
                        "taskId": task.get("id"),
                        "referenceImageId": reference_id,
                        "reverseVersionId": str(version.id),
                    },
                    prompt_snapshot={"finalPrompt": prompt},
                    config_snapshot={
                        "aspectRatio": aspect_ratio,
                        "resolution": resolution,
                        "outputLanguage": output_settings.get("outputLanguage", "中文"),
                        "modelId": output_settings.get("model"),
                    },
                )
            task.update(
                {
                    "status": "succeeded",
                    "generatedAssetId": str(generated.id),
                    "generatedPreviewUrl": f"/api/projects/{project.id}/assets/{generated.id}/preview",
                    "generatedAt": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            task["status"] = "failed"
            task["error"] = exc.message if isinstance(exc, AppError) else str(exc)

    async def _require_project(self, project_id: UUID) -> Any:
        workspace_id = self.identity_provider.get_context().workspace_id
        project = await self.project_repository.get_project(project_id, workspace_id)
        if project is None:
            raise AppError("INVALID_PROJECT_ID", "项目不存在", 404)
        return project

    async def _resolve_source(self, project_id: UUID, source_asset_id: UUID | None) -> Any:
        if source_asset_id is not None:
            asset, _ = await self.project_asset_service.get_asset_details(project_id, source_asset_id)
            return asset
        selections = await self.project_asset_service.get_selections(project_id)
        for role in ("white_background", "source"):
            selected_id = selections.get(role)
            if selected_id is not None:
                asset, _ = await self.project_asset_service.get_asset_details(project_id, selected_id)
                return asset
        assets = await self.project_asset_service.list_assets(project_id)
        fallback = next((asset for asset in assets if asset.kind in {"white_background", "source"}), None)
        if fallback is None:
            raise AppError("REVERSE_SOURCE_ASSET_REQUIRED", "请先准备商品原图或白底图", 400)
        return fallback
