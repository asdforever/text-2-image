"""编辑任务执行器：将排队任务交给图片编辑 Provider。"""

from typing import Any
from uuid import UUID, uuid4

from .hero_generation_ports import ImageEditInput, ImageEditRequest, ImageEditResult
from .image_editing_rendering import execute_operations, load_image
from ..core.errors import AppError
from ..image_editing_repository import ImageEditVersionRecord
from ..project_storage import project_asset_object_key
from ..storage import StoredObject


class ImageEditingWorker:
    def __init__(
        self,
        repository: Any,
        project_repository: Any,
        storage: Any,
        service: Any,
        image_editor: Any,
        project_asset_service: Any | None = None,
        project_output_archive: Any | None = None,
    ) -> None:
        self.repository = repository
        self.project_repository = project_repository
        self.storage = storage
        self.service = service
        self.image_editor = image_editor
        self.project_asset_service = project_asset_service
        self.project_output_archive = project_output_archive

    async def process_task(self, task_id: UUID) -> Any:
        workspace_id = self.service._workspace_id()
        task = await self.repository.get_task(task_id, workspace_id)
        if task is None:
            raise AppError("IMAGE_EDIT_TASK_NOT_FOUND", "图片编辑任务不存在", 404)
        attempt = task.attempts[-1]
        if not await self.repository.claim_attempt(task.id, attempt.id, workspace_id):
            return task
        source_asset = await self.project_repository.get_asset(UUID(task.source_snapshot["assetId"]), workspace_id)
        source_object = await self.project_repository.get_object(source_asset.object_id, workspace_id) if source_asset else None
        source_stored = await self.storage.get(source_object.storage_key) if source_object else None
        if source_stored is None:
            await self.repository.complete_attempt(task.id, attempt.id, success=False, error="源图片对象不存在")
            return task
        config = task.config_snapshot
        generation_params = config.get("generationParams")
        parameters = generation_params if isinstance(generation_params, dict) else config
        ratio = str(parameters.get("ratio") or parameters.get("aspectRatio") or "1:1")
        resolution = str(parameters.get("size") or parameters.get("resolution") or "标准 1K")
        edit_prompts = [str(item.get("payload", {}).get("prompt", "")).strip() for item in task.operations_snapshot if item.get("type") == "re_edit"]
        request = ImageEditRequest(
            prompt="\n".join(prompt for prompt in edit_prompts if prompt) or str(task.prompt_snapshot.get("summary", "")),
            image_bytes=source_stored.data,
            image_mime_type=source_stored.content_type,
            image_filename=source_object.original_filename,
            aspect_ratio=ratio,
            resolution=resolution,
            image_inputs=(ImageEditInput(source_stored.data, source_stored.content_type, source_object.original_filename),),
            model_connection=config.get("modelConnection") or parameters.get("modelConnection"),
        )
        try:
            final_prompt = request.prompt
            if any(item.get("payload", {}).get("schemaVersion") == 2 for item in task.operations_snapshot):
                data, final_prompt = await execute_operations(source_stored.data, task.operations_snapshot, self.image_editor,
                    ratio=ratio, resolution=resolution, connection=request.model_connection)
                result = ImageEditResult(data, "image/png", {})
            else:
                result = await self.image_editor.edit(request)
            output_size = load_image(result.image_bytes).size
            version_id = uuid4()
            key = f"image-edit/{workspace_id}/{task.project_id}/{task.id}/{version_id}.png"
            await self.storage.put(StoredObject(key, result.image_bytes, result.image_mime_type))
            version = ImageEditVersionRecord(
                id=version_id,
                task_id=task.id,
                attempt_id=attempt.id,
                version_number=len(task.versions) + 1,
                object_key=key,
                preview_url=await self.storage.preview_url(key),
                source_snapshot={**task.source_snapshot, "width": output_size[0], "height": output_size[1]},
                prompt_snapshot={**task.prompt_snapshot, "finalPrompt": final_prompt},
                config_snapshot=dict(task.config_snapshot),
            )
            if task.config_snapshot.get("outputKind") == "canvas_edit":
                if self.project_asset_service is None:
                    raise RuntimeError("画布图片资产服务不可用")
                asset = await self.project_asset_service.create_generated_asset(
                    task.project_id, result.image_bytes, result.image_mime_type,
                    f"画布编辑-{version.version_number}-{source_object.original_filename}",
                    source_asset_id=source_asset.id, generation_snapshot_id=version_id,
                )
                version.preview_url = f"/api/projects/{task.project_id}/assets/{asset.id}/preview"
                version.source_snapshot = {**version.source_snapshot, "outputAssetId": str(asset.id)}
                if self.project_output_archive is not None:
                    project = await self.project_repository.get_project(task.project_id, workspace_id)
                    await self.project_output_archive.archive_project_output(
                        project_id=task.project_id, project_name=project.name if project else "项目成品", product_type="edit",
                        source_version_id=asset.id, preview_url=version.preview_url,
                        source_snapshot={"assetId": str(asset.id), "imageEditTaskId": str(task.id), "imageEditVersionId": str(version.id)},
                        prompt_snapshot={**task.prompt_snapshot, "finalPrompt": final_prompt}, config_snapshot=dict(task.config_snapshot),
                    )
            await self.repository.add_version(task.id, version)
            if task.config_snapshot.get("outputKind") == "white_background":
                if self.project_asset_service is None:
                    raise RuntimeError("白底图项目资产服务不可用")
                asset = await self.project_asset_service.upload_asset(
                    task.project_id,
                    "white_background",
                    result.image_bytes,
                    result.image_mime_type,
                    str(task.config_snapshot.get("outputFilename") or f"{source_object.original_filename}-白底图.png"),
                    source_asset_id=UUID(task.source_snapshot["assetId"]),
                    source_kind="generated",
                    source_snapshot={
                        "imageEditTaskId": str(task.id),
                        "imageEditVersionId": str(version.id),
                        "promptSnapshot": dict(task.prompt_snapshot),
                    },
                )
                if self.project_output_archive is not None:
                    project = await self.project_repository.get_project(task.project_id, workspace_id)
                    await self.project_output_archive.archive_project_output(
                        project_id=task.project_id,
                        project_name=project.name if project is not None else "项目成品",
                        product_type="white_background",
                        source_version_id=asset.id,
                        preview_url=f"/api/projects/{task.project_id}/assets/{asset.id}/preview",
                        source_snapshot={
                            "assetId": str(asset.id),
                            "imageEditTaskId": str(task.id),
                            "imageEditVersionId": str(version.id),
                        },
                        prompt_snapshot=dict(task.prompt_snapshot),
                        config_snapshot=dict(task.config_snapshot),
                    )
            await self.repository.complete_attempt(task.id, attempt.id, success=True)
            return task
        except Exception as exc:
            await self.repository.complete_attempt(task.id, attempt.id, success=False, error=str(exc))
            return task
