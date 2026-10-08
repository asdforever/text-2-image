"""Generate project assets from the project reverse execution plan."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from ..core.errors import AppError
from ..reverse_execution_repository import ReverseExecutionPlanRecord
from ..reverse_execution_batch_repository import MemoryReverseBatchRepository
from .hero_generation_ports import ImageEditInput, ImageEditRequest
from .reverse_execution import compile_task_prompt
from .reverse_product_images import image_snapshot, load_product_images


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
        batch_repository: Any | None = None,
        timeout_ms: int = 1_800_000,
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
        self.batch_repository = batch_repository or MemoryReverseBatchRepository()
        self.timeout_ms = timeout_ms

    def _deadline(self):
        return (datetime.now(timezone.utc) + timedelta(milliseconds=self.timeout_ms, seconds=120)).isoformat()

    async def list_batches(self, project_id, plan_id=None):
        await self._require_project(project_id)
        if plan_id is not None and await self.plan_service.get(project_id, plan_id) is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "反推方案不存在", 404)
        scope = self.identity_provider.get_context().workspace_id
        records = await self.batch_repository.list(scope, project_id, plan_id)
        for record in records:
            document = record.document
            if document.get("status") != "running" or not document.get("leaseExpiresAt") or datetime.fromisoformat(document["leaseExpiresAt"]) >= datetime.now(timezone.utc):
                continue
            for task in document.get("tasks", []):
                if task["status"] in {"queued", "generating"}:
                    task.update(status="failed", error="生成中断或超时，可在此批次重试")
                    for attempt in task.get("attempts", []):
                        if attempt["status"] == "generating":
                            attempt.update(status="failed", error=task["error"])
            document["status"] = "partial" if any(task["status"] == "succeeded" for task in document.get("tasks", [])) else "failed"
            try:
                await self.batch_repository.save(record, document)
            except AppError as exc:
                if exc.code != "REVERSE_BATCH_REVISION_CONFLICT":
                    raise
        return await self.batch_repository.list(scope, project_id, plan_id)

    async def get_batch(self, project_id, batch_id, plan_id=None):
        await self._require_project(project_id)
        record = await self.batch_repository.get(self.identity_provider.get_context().workspace_id, project_id, batch_id, plan_id)
        if record is None:
            raise AppError("REVERSE_BATCH_NOT_FOUND", "反推批次不存在", 404)
        return record

    async def generate(
        self,
        project_id: UUID,
        expected_revision: int,
        *,
        task_ids: Iterable[str] | None = None,
        source_asset_id: UUID | None = None,
        auxiliary_source_asset_ids: list[UUID] | None = None,
        aspect_ratio: str = "1:1",
        resolution: str = "标准 1K",
        plan_id: UUID | None = None,
        batch_id: UUID | None = None,
    ) -> ReverseExecutionPlanRecord:
        plan = await self.plan_service.get(project_id, plan_id)
        if plan is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        if plan.revision != expected_revision:
            raise AppError("REVERSE_EXECUTION_REVISION_CONFLICT", "项目反推方案已被更新，请重新加载", 409)
        project = await self._require_project(project_id)
        await self.list_batches(project_id, plan.id)
        batch = await self.get_batch(project_id, batch_id, plan.id) if batch_id else None
        selected = set(task_ids) if task_ids is not None else None
        document = deepcopy(batch.document if batch else plan.document)
        available_tasks = {task["id"] for task in document.get("tasks", [])}
        if not available_tasks or (selected is not None and (not selected or not selected.issubset(available_tasks))):
            raise AppError("REVERSE_EXECUTION_TASKS_INVALID", "请选择当前方案或批次中的有效任务", 400)
        if batch and selected is None:
            raise AppError("REVERSE_EXECUTION_TASKS_INVALID", "批次重试必须选择具体任务", 400)
        saved_source_id = document.get("sourceAssetId")
        if batch:
            source_asset_id = None  # Retry always uses the original batch input.
        source = await self._resolve_source(project_id, source_asset_id or (UUID(saved_source_id) if saved_source_id else None))
        source_asset, source_object = await self.project_asset_service.get_asset_details(project_id, source.id)
        source_stored = await self.project_asset_service.get_preview(project_id, source.id)
        auxiliary_ids = await self.plan_service.validate_auxiliary_assets(project_id,
            document.get("auxiliarySourceAssetIds", []) if batch or auxiliary_source_asset_ids is None else auxiliary_source_asset_ids, source.id)
        auxiliary_inputs, auxiliary_snapshots = await load_product_images(self.project_asset_service, project_id, auxiliary_ids)
        product_inputs = (ImageEditInput(source_stored.data, source_object.media_type, source_object.original_filename), *auxiliary_inputs)
        product_snapshots = [image_snapshot(source.id, source_object, source_stored), *auxiliary_snapshots]
        if len(product_inputs) > 1 and not getattr(self.image_editor, "supports_multiple_source_images", True):
            raise AppError("REVERSE_PRODUCT_IMAGES_UNSUPPORTED", "当前生图模型不支持多张商品素材，请选择支持多图输入的模型", 400)
        if batch and document.get("productImages") and document["productImages"] != product_snapshots:
            raise AppError("REVERSE_PRODUCT_IMAGES_CHANGED", "该批次的商品素材已变化，不能替换原素材重试，请创建新批次", 409)
        version = await self.reverse_project_service.get_version(UUID(document["versionId"]))
        references = {str(item["id"]): item for item in version.document.get("references", [])}
        product_facts = {"商品名称": project.name, **document.get("productFacts", {})}
        document["sourceAssetId"] = str(source.id)
        document["auxiliarySourceAssetIds"] = auxiliary_ids
        output_settings = document.get("outputSettings") or {}
        requested_model = output_settings.get("model")
        effective_aspect_ratio = document["aspectRatio"] if batch else aspect_ratio if aspect_ratio != "1:1" else output_settings.get("aspectRatio", aspect_ratio)
        effective_resolution = document["resolution"] if batch else resolution if resolution != "标准 1K" else output_settings.get("resolution", resolution)
        model_connection = document.get("modelConnection") if batch else await self.model_connections.snapshot(requested_model) if self.model_connections is not None else None

        if batch:
            batch = await self.batch_repository.claim(batch, self._deadline())
            document = deepcopy(batch.document)
        else:
            if document.get("sourceAssetId") != plan.document.get("sourceAssetId") or auxiliary_ids != plan.document.get("auxiliarySourceAssetIds", []):
                plan = await self.plan_service.save(project_id, expected_revision, document, plan_id=plan.id)
                expected_revision = plan.revision
                document = deepcopy(plan.document)
            if document.get("parameterBrief", "").strip() and not document.get("parametersAssigned"):
                plan = await self.plan_service.assign_parameters(project_id, expected_revision, plan_id=plan.id)
                expected_revision = plan.revision
                document = deepcopy(plan.document)
                document["sourceAssetId"] = str(source.id)
                document["auxiliarySourceAssetIds"] = auxiliary_ids
            document.update(status="running", planName=document.get("name", "反推方案"),
                productImages=product_snapshots,
                leaseExpiresAt=self._deadline(), productFacts=product_facts,
                aspectRatio=effective_aspect_ratio, resolution=effective_resolution, modelConnection=model_connection,
                requestedTaskIds=list(selected) if selected is not None else list(available_tasks))
            for task in document["tasks"]:
                task["promptDraft"] = compile_task_prompt(task, product_facts, output_settings, product_image_count=len(product_inputs))
                task["attempts"] = []
                task["status"] = "queued" if selected is None or task["id"] in selected else "not_requested"
                for field in ("generatedAssetId", "generatedPreviewUrl", "generatedAt", "error"):
                    task.pop(field, None)
            batch = await self.batch_repository.create(self.identity_provider.get_context().workspace_id, project_id, plan.id, document)

        for task in document.get("tasks", []):
            if selected is not None and task.get("id") not in selected:
                continue
            attempt = {"id": str(uuid4()), "number": len(task["attempts"]) + 1,
                "status": "generating", "createdAt": datetime.now(timezone.utc).isoformat()}
            task["attempts"].append(attempt)
            document["leaseExpiresAt"] = self._deadline()
            task["status"] = "generating"
            batch = await self.batch_repository.save(batch, document)
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
                batch,
                attempt,
                product_inputs,
            )
            attempt.update({key: deepcopy(task[key]) for key in ("status", "generatedAssetId", "generatedPreviewUrl", "generatedAt", "error", "archiveError")
                if key in task and (task["status"] == "succeeded" or key in {"status", "error"})})
            attempt["completedAt"] = datetime.now(timezone.utc).isoformat()
            batch = await self.batch_repository.save(batch, document)

        # A single revision is committed for the complete request so the UI can
        # refresh once and still keep optimistic concurrency intact.
        requested_tasks = [task for task in document["tasks"] if task["status"] != "not_requested"]
        succeeded = sum(task["status"] == "succeeded" for task in requested_tasks)
        document["status"] = "completed" if succeeded == len(requested_tasks) else "partial" if succeeded else "failed"
        document["completedAt"] = datetime.now(timezone.utc).isoformat()
        await self.batch_repository.save(batch, document)
        # Old batch retries never overwrite an independently edited plan.
        if batch_id is not None:
            return await self.plan_service.get(project_id, plan.id)
        next_plan = deepcopy(plan.document)
        next_plan["sourceAssetId"] = str(source.id)
        next_plan["auxiliarySourceAssetIds"] = auxiliary_ids
        next_plan["lastBatchId"] = str(batch.id)
        next_plan["tasks"] = [{key: value for key, value in task.items() if key != "attempts"} for task in document["tasks"]]
        try:
            return await self.plan_service.save(project_id, expected_revision, next_plan, plan_id=plan.id)
        except AppError as exc:
            if exc.code != "REVERSE_EXECUTION_REVISION_CONFLICT":
                raise
            return await self.plan_service.get(project_id, plan.id)

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
        batch: Any,
        attempt: dict[str, Any],
        product_inputs: tuple[ImageEditInput, ...],
    ) -> None:
        task["status"] = "generating"
        for field in ("error", "archiveError", "generatedAssetId", "generatedPreviewUrl", "generatedAt"):
            task.pop(field, None)
        reference_id = str(task.get("referenceImageId"))
        reference = references.get(reference_id)
        try:
            if reference is None:
                raise AppError("REVERSE_REFERENCE_NOT_FOUND", "反推模板图不存在", 404)
            prompt = str(task.get("promptDraft") or compile_task_prompt(task, product_facts, output_settings))
            task["promptDraft"] = prompt
            result = await self.image_editor.edit(
                ImageEditRequest(
                    prompt=prompt,
                    image_bytes=source_stored.data,
                    image_mime_type=source_object.media_type,
                    image_filename=source_object.original_filename,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    image_inputs=product_inputs,
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
                generation_snapshot_id=batch.id,
                source_kind="reverse_execution",
                source_snapshot={
                    "sourceAssetIds": [item["assetId"] for item in batch.document.get("productImages", [])],
                    "productImages": deepcopy(batch.document.get("productImages", [])),
                    "reverseExecutionPlanId": str(plan_id),
                    "reverseExecutionBatchId": str(batch.id),
                    "batchId": str(batch.id),
                    "batchNo": batch.batch_no,
                    "batchCreatedAt": batch.created_at.isoformat(),
                    "reverseExecutionAttemptId": attempt["id"],
                    "promptSnapshot": {"finalPrompt": prompt},
                    "outputSettings": {**output_settings, "aspectRatio": aspect_ratio, "resolution": resolution},
                    "reverseVersionId": str(version.id),
                    "taskId": task.get("id"),
                    "referenceImageId": reference_id,
                    "moduleId": task.get("referenceModuleId"),
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
            if self.project_archive is not None:
                await self.project_archive.archive_project_output(
                    project_id=project.id,
                    project_name=project.name,
                    product_type="detail",
                    source_version_id=generated.id,
                    preview_url=f"/api/projects/{project.id}/assets/{generated.id}/preview",
                    source_snapshot={
                        "sourceAssetIds": [item["assetId"] for item in batch.document.get("productImages", [])],
                        "productImages": deepcopy(batch.document.get("productImages", [])),
                        "sourceKind": "reverse_execution",
                        "reverseExecutionPlanId": str(plan_id),
                        "reverseExecutionBatchId": str(batch.id),
                        "batchId": str(batch.id),
                        "reverseExecutionAttemptId": attempt["id"],
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
        except Exception as exc:
            message = exc.message if isinstance(exc, AppError) else str(exc)
            if task.get("generatedAssetId"):
                # A durable project image exists; archive failure must not invite
                # another provider call by misreporting generation as failed.
                task["archiveError"] = message
            else:
                task["status"] = "failed"
                task["error"] = message

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
