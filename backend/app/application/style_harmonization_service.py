"""只对选中图片执行轻量风格调整；结果为独立候选素材，不修改任何选择。"""
import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from math import log
from uuid import UUID, uuid4, uuid5

from PIL import Image, ImageOps

from ..core.errors import AppError
from .hero_generation_ports import ImageEditInput, ImageEditRequest
from .hero_prompting import PRODUCT_AUTHENTICITY_CONSTRAINT
from .idempotency import request_fingerprint


PREFIX = "style-harmonization:"
PROVIDER_RATIOS = {"1:1": 1, "3:4": 3 / 4, "4:3": 4 / 3, "16:9": 16 / 9}
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_EDGE = 16384
MAX_IMAGE_BYTES = 64 * 1024 * 1024
LIGHT_EDIT_GUARD = (
    "只调整第一张图片的色调、光照、背景质感和整体视觉风格。"
    "保留原商品身份、结构、颜色、材质、全部文字内容、文字位置、构图和布局；"
    "不增加或删除商品、文字及功能，不重新设计版式，不拼接成长图。"
    "若风格要求与以上保留约束冲突，以保留约束为准。"
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _deadline():
    return (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()


def _check_dimensions(width, height):
    if width < 1 or height < 1 or width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE or width * height > MAX_IMAGE_PIXELS:
        raise AppError("STYLE_IMAGE_TOO_LARGE", "风格图片须不超过 4000 万像素，且单边不超过 16384 像素", 400)


def _check_image(body, expected=None):
    if not body or len(body) > MAX_IMAGE_BYTES:
        raise AppError("STYLE_IMAGE_TOO_LARGE", "风格图片文件须不超过 64 MB", 400)
    with Image.open(BytesIO(body)) as image:
        _check_dimensions(*image.size)
        if expected is not None and image.size != expected:
            raise AppError("STYLE_SOURCE_CHANGED", "图片尺寸与提交时的冻结版本不一致", 409)
        image.verify()


def _display_size(body):
    _check_image(body)
    with Image.open(BytesIO(body)) as image:
        width, height = image.size
        return (height, width) if image.getexif().get(274) in {5, 6, 7, 8} else (width, height)


def _candidate_image(body, width, height):
    """后台线程中校验并等比补边；不裁剪、不拉伸模型返回的商品。"""
    _check_dimensions(width, height)
    _check_image(body)
    with Image.open(BytesIO(body)) as rendered:
        contained = ImageOps.contain(ImageOps.exif_transpose(rendered).convert("RGBA"), (width, height), Image.Resampling.LANCZOS)
        normalized = Image.new("RGB", (width, height), "white")
        normalized.paste(contained, ((width - contained.width) // 2, (height - contained.height) // 2), contained)
        stream = BytesIO()
        normalized.save(stream, format="PNG")
        result = stream.getvalue()
        if len(result) > MAX_IMAGE_BYTES:
            raise AppError("STYLE_IMAGE_TOO_LARGE", "风格候选文件超过 64 MB，请降低源图尺寸", 400)
        return result


def _status(job):
    statuses = [task["status"] for task in job["tasks"]]
    if any(status in {"queued", "generating"} for status in statuses):
        return "generating" if "generating" in statuses else "queued"
    return "succeeded" if all(s == "succeeded" for s in statuses) else "partial" if "succeeded" in statuses else "failed"


def _expire(job):
    if job["status"] in {"queued", "generating"} and job["leaseExpiresAt"] < _now():
        for task in job["tasks"]:
            if task["status"] in {"queued", "generating"}:
                task.update(status="failed", error="生成任务已中断，请确认后重新提交；不会自动重试")
            _finish_archive(task)
        job["status"] = _status(job)


def _finish_archive(task):
    if task["status"] == "succeeded" and task.get("archiveStatus") == "pending":
        message = "候选图片已保存，但归档过程已中断；可继续使用候选，请勿重复生成"
        task.update(archiveStatus="failed", error=message, archiveError=message)


class StyleHarmonizationService:
    def __init__(self, repository, projects, storage, assets, editor, archive, identity, provider_model, prompts, model_connections=None):
        self.repository, self.projects, self.storage, self.assets = repository, projects, storage, assets
        self.editor, self.archive, self.identity = editor, archive, identity
        self.provider_model, self.prompts = provider_model, prompts
        self.model_connections = model_connections

    @property
    def scope(self):
        return self.identity.get_context().workspace_id

    async def _project(self, project_id):
        project = await self.projects.get_project(project_id, self.scope)
        if project is None or project.status != "active":
            raise AppError("STYLE_PROJECT_NOT_FOUND", "项目不存在或已归档", 404)
        return project

    async def _source(self, project_id, asset_id):
        try:
            parsed = UUID(str(asset_id))
        except (ValueError, TypeError):
            raise AppError("STYLE_SOURCE_INVALID", "图片标识无效", 400) from None
        asset = await self.projects.get_asset(parsed, self.scope)
        obj = await self.projects.get_object(asset.object_id, self.scope) if asset else None
        if not asset or asset.project_id != project_id or asset.state != "available" or not obj or obj.state != "available":
            raise AppError("STYLE_SOURCE_UNAVAILABLE", "图片不存在、已删除或不属于当前项目", 409)
        _check_dimensions(obj.width, obj.height)
        if obj.byte_size > MAX_IMAGE_BYTES:
            raise AppError("STYLE_IMAGE_TOO_LARGE", "风格图片文件须不超过 64 MB", 400)
        stored = await self.storage.get(obj.storage_key)
        if not stored or sha256(stored.data).hexdigest() != obj.sha256:
            raise AppError("STYLE_SOURCE_CHANGED", "图片内容与保存的版本不一致", 409)
        display_width, display_height = await asyncio.to_thread(_display_size, stored.data)
        return {"assetId": str(asset.id), "objectId": str(obj.id), "sha256": obj.sha256,
                "filename": obj.original_filename, "mimeType": obj.media_type,
                "width": obj.width, "height": obj.height,
                "displayWidth": display_width, "displayHeight": display_height}

    async def list_jobs(self, project_id):
        await self._project(project_id)
        records = await self.repository.list(project_id, self.scope)
        jobs = []
        for record in records:
            if record.get("kind") != "style-harmonization":
                continue
            def recover(state):
                _expire(state["job"])
                return state["job"]
            jobs.append(await self.repository.change(project_id, self.scope, record["stepId"], None, recover))
        return sorted(jobs, key=lambda item: item["createdAt"], reverse=True)

    async def preview(self, project_id, payload):
        job = await self.submit(project_id, payload, str(uuid4()), preview_only=True)
        return {key: job[key] for key in ("finalPrompt", "assetIds", "mode", "promptSnapshot", "referenceAsset", "previewHash")}

    async def submit(self, project_id, payload, request_key, *, preview_only=False):
        await self._project(project_id)
        if not isinstance(request_key, str) or not request_key.strip() or len(request_key) > 200:
            raise AppError("STYLE_IDEMPOTENCY_REQUIRED", "请提供有效的提交标识", 400)
        sources, mode = payload.get("assetIds"), payload.get("mode")
        if not isinstance(sources, list) or not 1 <= len(sources) <= 20 or any(not isinstance(s, str) for s in sources) or len(set(sources)) != len(sources):
            raise AppError("STYLE_SELECTION_INVALID", "请选择 1 至 20 张不重复的图片", 400)
        if not isinstance(mode, str) or mode not in {"reference", "prompt", "custom"}:
            raise AppError("STYLE_MODE_INVALID", "风格统一方式无效", 400)
        fingerprint = request_fingerprint(payload)
        job_id = str(uuid5(project_id, f"{self.scope}:{request_key}"))
        step_id = PREFIX + job_id
        for old in ([] if preview_only else await self.list_jobs(project_id)):
            if old["id"] == job_id:
                if old["fingerprint"] != fingerprint:
                    raise AppError("IDEMPOTENCY_KEY_CONFLICT", "该提交标识已用于不同内容", 409)
                return old
        frozen = [await self._source(project_id, asset_id) for asset_id in sources]
        if len({item["assetId"] for item in frozen}) != len(frozen):
            raise AppError("STYLE_SELECTION_INVALID", "请选择不重复的图片", 400)
        reference = None
        if mode == "reference":
            reference = await self._source(project_id, payload.get("referenceAssetId"))
            if not getattr(self.editor, "supports_multiple_source_images", False):
                raise AppError("STYLE_REFERENCE_UNSUPPORTED", "当前模型不支持参考图所需的多图片输入", 409)
            content = "参考第二张图片的色调、光照及背景质感，对第一张图片进行轻量调整；第二张只作为风格参考，不复制其商品或文字。"
            prompt_snapshot = {"source": "reference", "content": content, "referenceAssetId": reference["assetId"], "referenceSha256": reference["sha256"]}
        elif mode == "prompt":
            try:
                version_id = UUID(str(payload.get("promptVersionId")))
            except (TypeError, ValueError):
                raise AppError("STYLE_PROMPT_INVALID", "请选择有效的风格提示词版本", 400) from None
            version = await self.prompts.get_version(version_id)
            if version is None:
                raise AppError("STYLE_PROMPT_NOT_FOUND", "风格提示词版本不存在", 404)
            from .prompt_usage import require_image_prompt
            require_image_prompt(version)
            runtime = version.user_prompt_template.strip()
            content = runtime or version.body
            prompt_snapshot = {"source": "prompt_version_user_template" if runtime else "prompt_version_body", "content": content,
                               "promptVersionId": str(version.id), "promptTemplateId": str(version.template_id), "promptVersionSha256": version.content_sha256,
                               "body": version.body, "userPromptTemplate": version.user_prompt_template}
        else:
            content = payload.get("prompt")
            prompt_snapshot = {"source": "custom", "content": content}
        if not isinstance(content, str) or not content.strip() or len(content) > 30000:
            raise AppError("STYLE_PROMPT_INVALID", "请填写完整风格提示词，且不超过 30000 个字符", 400)
        prompt_snapshot["contentSha256"] = sha256(content.encode()).hexdigest()
        final_prompt = f"[商品真实性约束]\n{PRODUCT_AUTHENTICITY_CONSTRAINT}\n\n[轻量编辑约束]\n{LIGHT_EDIT_GUARD}\n\n[完整风格要求]\n{content}"
        tasks = []
        from .model_connection_service import model_selection_id
        connection = await self.model_connections.snapshot(model_selection_id(payload.get("modelId"))) if self.model_connections else None
        for source in frozen:
            # 使用模型支持的最接近比例，最终候选还原到源图精确像素大小。
            ratio = source["displayWidth"] / source["displayHeight"]
            supported_ratios = (connection or {}).get("aspectRatios") or list(PROVIDER_RATIOS)
            aspect = min(supported_ratios, key=lambda key: abs(log(ratio / PROVIDER_RATIOS[key])))
            edge = max(source["width"], source["height"])
            resolution = "超清 4K" if edge > 2400 else "高清 2K" if edge > 1200 else "标准 1K"
            from ..core.image_dimensions import RESOLUTION_LEVELS, normalize_resolution
            supported_resolutions = [normalize_resolution(item) for item in (connection or {}).get("resolutions", [])]
            if supported_resolutions and resolution not in supported_resolutions:
                resolution = min(supported_resolutions, key=lambda item: abs(RESOLUTION_LEVELS[item] - RESOLUTION_LEVELS[resolution]))
            tasks.append({"id": str(uuid4()), "sourceAssetId": source["assetId"], "sourceAsset": source, "status": "queued", "outputAssetId": None, "error": None, "archiveStatus": "pending", "archiveError": None,
                          "parameters": {"aspectRatio": aspect, "resolution": resolution, "width": source["displayWidth"], "height": source["displayHeight"], "providerModel": connection["modelName"] if connection else self.provider_model, **({"modelConnection": connection} if connection else {})}})
        preview_hash = request_fingerprint({"finalPrompt": final_prompt, "promptSnapshot": prompt_snapshot, "sourceAssets": frozen, "referenceAsset": reference, "parameters": [task["parameters"] for task in tasks]})
        expected_hash = payload.get("expectedPreviewHash")
        if not preview_only and expected_hash is not None and expected_hash != preview_hash:
            raise AppError("STYLE_PREVIEW_CHANGED", "提示词或图片版本已变化，请重新预览并确认", 409)
        job = {"id": job_id, "projectId": str(project_id), "mode": mode, "status": "queued", "assetIds": list(sources), "referenceAsset": reference,
               "promptSnapshot": prompt_snapshot, "finalPrompt": final_prompt, "previewHash": preview_hash, "tasks": tasks, "createdAt": _now(), "leaseExpiresAt": _deadline(), "fingerprint": fingerprint}
        if preview_only:
            return job
        # 独立命名空间与空选择字段使这些记录永远不会形成画布版本替换。
        initial = {"stepId": step_id, "kind": "style-harmonization", "title": "局部风格统一", "revisions": [], "currentAssetIds": [], "originalAssetIds": [], "job": job}
        def insert(state):
            if state["job"]["fingerprint"] != fingerprint:
                raise AppError("IDEMPOTENCY_KEY_CONFLICT", "该提交标识已用于不同内容", 409)
            return state["job"]
        return await self.repository.change(project_id, self.scope, step_id, initial, insert)

    async def _input(self, project_id, snapshot):
        current = await self._source(project_id, snapshot["assetId"])
        obj = await self.projects.get_object(UUID(snapshot["objectId"]), self.scope)
        stored = await self.storage.get(obj.storage_key) if obj else None
        if current != snapshot or not stored or sha256(stored.data).hexdigest() != snapshot["sha256"]:
            raise AppError("STYLE_SOURCE_CHANGED", "图片内容与提交时的冻结版本不一致", 409)
        await asyncio.to_thread(_check_image, stored.data, (snapshot["width"], snapshot["height"]))
        return ImageEditInput(stored.data, snapshot["mimeType"], snapshot["filename"])

    async def execute(self, project_id, job_id):
        step_id = PREFIX + job_id
        async def change(action):
            return await self.repository.change(project_id, self.scope, step_id, None, lambda state: action(state["job"]))
        def claim(job):
            _expire(job)
            if job["status"] != "queued":
                return None
            job.update(status="generating", leaseExpiresAt=_deadline())
            return job
        job = await change(claim)
        if job is None:
            return
        async def heartbeat():
            while True:
                await asyncio.sleep(20)
                await change(lambda current: current.update(leaseExpiresAt=_deadline()) if current["status"] == "generating" else None)
        heart = asyncio.create_task(heartbeat())
        interrupted = False
        try:
            project = await self._project(project_id)
            for task in job["tasks"]:
                created = None
                def start(current):
                    _expire(current)
                    if current["status"] != "generating":
                        return False
                    next(t for t in current["tasks"] if t["id"] == task["id"])["status"] = "generating"
                    return True
                if not await change(start):
                    break
                try:
                    inputs = [await self._input(project_id, task["sourceAsset"])]
                    if job["referenceAsset"]:
                        inputs.append(await self._input(project_id, job["referenceAsset"]))
                    params = task["parameters"]
                    request = ImageEditRequest(job["finalPrompt"], inputs[0].image_bytes, inputs[0].image_mime_type, inputs[0].image_filename, params["aspectRatio"], params["resolution"], tuple(inputs), model_connection=params.get("modelConnection"))
                    result = await self.editor.edit(request)
                    candidate_bytes = await asyncio.to_thread(_candidate_image, result.image_bytes, params["width"], params["height"])
                    provenance = {"styleHarmonizationId": job_id, "styleHarmonizationTaskId": task["id"], "sourceAssetId": task["sourceAssetId"], "referenceAsset": job["referenceAsset"]}
                    created = await self.assets.create_generated_asset(project_id, candidate_bytes, "image/png", f"风格候选-{task['id']}.png", source_asset_id=UUID(task["sourceAssetId"]), generation_snapshot_id=UUID(task["id"]), source_kind="generated", source_snapshot=provenance, max_output_bytes=MAX_IMAGE_BYTES)
                    def complete_task(current):
                        if current["status"] != "generating":
                            raise AppError("STYLE_TASK_INTERRUPTED", "风格任务已中断，请重新提交", 409)
                        next(t for t in current["tasks"] if t["id"] == task["id"]).update(status="succeeded", outputAssetId=str(created.id))
                    await change(complete_task)
                    try:
                        await self.archive.archive_project_output(project_id=project_id, project_name=project.name, product_type="edit", source_version_id=created.id,
                            preview_url=f"/api/projects/{project_id}/assets/{created.id}/preview", source_snapshot=provenance | {"assetId": str(created.id)},
                            prompt_snapshot=job["promptSnapshot"] | {"finalPrompt": job["finalPrompt"]}, config_snapshot=params)
                    except Exception:
                        def archive_failed(current):
                            message = "候选图片已保存，但成品库归档失败；可继续使用候选，请勿重复生成"
                            next(t for t in current["tasks"] if t["id"] == task["id"]).update(archiveStatus="failed", error=message, archiveError=message)
                        await change(archive_failed)
                    else:
                        await change(lambda current: next(t for t in current["tasks"] if t["id"] == task["id"]).update(archiveStatus="succeeded"))
                except (Exception, asyncio.CancelledError) as exc:
                    # 资产写入后的项目成品链接可能失败：按任务标识找回已经保存的付费结果。
                    if created is None:
                        created = next((asset for asset in await self.assets.list_assets(project_id)
                            if asset.state == "available" and asset.generation_snapshot_id == UUID(task["id"])
                            and (asset.source_snapshot or {}).get("styleHarmonizationTaskId") == task["id"]), None)
                    def fail_task(current):
                        record = next(t for t in current["tasks"] if t["id"] == task["id"])
                        if created:
                            message = "候选图片已保存，后续记录或归档未完成；请勿重复生成"
                            record.update(status="succeeded", outputAssetId=str(created.id), archiveStatus="failed", error=message, archiveError=message)
                        else:
                            record.update(status="failed", error="风格生成或保存失败，请检查图片与模型服务后明确重新提交")
                    await change(fail_task)
                    if isinstance(exc, asyncio.CancelledError):
                        raise
        except asyncio.CancelledError:
            interrupted = True
        except Exception:
            pass
        finally:
            heart.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await heart
            def finish(current):
                for task in current["tasks"]:
                    if task["status"] in {"queued", "generating"}:
                        task.update(status="failed", error="风格任务已中断，已保存的候选保留；不会自动重试")
                    _finish_archive(task)
                current["status"] = _status(current)
            await change(finish)
        if interrupted:
            raise asyncio.CancelledError()
