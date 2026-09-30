"""从冻结的上游输入重新生成，原图和历史提示词均不覆写。"""
import asyncio
from contextlib import suppress
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from ..core.errors import AppError
from .hero_generation_ports import ImageEditInput, ImageEditRequest
from .idempotency import request_fingerprint
from .hero_prompting import restore_bound_constraints


def now():
    return datetime.now(timezone.utc).isoformat()


def lease_deadline():
    return (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()


def expire_revisions(state):
    for version in state["revisions"]:
        if version["status"] in {"queued", "generating"} and version.get("leaseExpiresAt", version["createdAt"]) < now():
            version.update(status="partial" if version["outputs"] else "failed", errors=[{"index": -1, "message": "生成任务已中断，已保存图片保留；请确认后重新生成，不会自动重试"}])


def compose_prompt(kind, constraints, task_prompt):
    if kind not in {"hero", "suite", "detail"}:
        return task_prompt
    cards = [("authenticity", "商品真实性约束"), ("market", "具体电商平台约束"), ("style", "全局风格约束")]
    parts = [f"[{label}]\n{constraints[key]['content']}" for key, label in cards if constraints.get(key, {}).get("content")]
    return "\n\n".join([*parts, f"[实时任务提示词]\n{task_prompt}"])


class CanvasGenerationService:
    def __init__(self, repository, projects, storage, assets, editor, archive, identity, load_steps, provider_model, prompt_repository=None, model_connections=None):
        self.repository, self.projects, self.storage, self.assets = repository, projects, storage, assets
        self.editor, self.archive, self.identity, self.load_steps, self.provider_model = editor, archive, identity, load_steps, provider_model
        self.prompt_repository = prompt_repository
        self.model_connections = model_connections

    async def preview_constraints(self, project_id, step_id, base_revision_id):
        await self.require_project(project_id)
        tracks = await self.repository.list(project_id, self.scope)
        track = next((t for t in tracks if t["stepId"] == step_id), None)
        if track:
            base = next((v for v in track["revisions"] if v["id"] == base_revision_id), None)
        else:
            base = next((s for s in await self.load_steps(project_id) if s["id"] == step_id), None) if base_revision_id == "original" else None
        if base is None:
            raise AppError("CANVAS_VERSION_NOT_FOUND", "提示词版本不存在，请刷新", 404)
        if self.prompt_repository is None:
            raise AppError("CANVAS_PROMPTS_UNAVAILABLE", "提示词服务不可用", 503)
        constraints = await restore_bound_constraints(base["constraints"], self.prompt_repository)
        return {"constraints": constraints, "constraintsHash": request_fingerprint(constraints)}

    @property
    def scope(self):
        return self.identity.get_context().workspace_id

    async def require_project(self, project_id):
        project = await self.projects.get_project(project_id, self.scope)
        if project is None or project.status != "active":
            raise AppError("CANVAS_PROJECT_NOT_FOUND", "项目不存在或已归档", 404)
        return project

    async def list_tracks(self, project_id):
        await self.require_project(project_id)
        return await self.recover_expired(project_id)

    async def recover_expired(self, project_id):
        tracks = [track for track in await self.repository.list(project_id, self.scope) if track.get("kind") != "style-harmonization"]
        for track in tracks:
            if any(v["status"] in {"queued", "generating"} and v.get("leaseExpiresAt", v["createdAt"]) < now() for v in track["revisions"]):
                def recover(state):
                    expire_revisions(state)
                    return state
                track.update(await self.repository.change(project_id, self.scope, track["stepId"], None, recover))
        return tracks

    async def source_snapshot(self, project_id, asset_id):
        asset = await self.projects.get_asset(UUID(asset_id), self.scope)
        obj = await self.projects.get_object(asset.object_id, self.scope) if asset else None
        if not asset or asset.project_id != project_id or asset.state != "available" or not obj or obj.state != "available":
            raise AppError("CANVAS_SOURCE_UNAVAILABLE", "上游图片不存在、已删除或不属于此项目", 409)
        return {"assetId": str(asset.id), "objectId": str(obj.id), "sha256": obj.sha256, "filename": obj.original_filename, "mimeType": obj.media_type}

    async def submit(self, project_id, step_id, base_revision_id, task_prompt, source_asset_ids, request_key, restored_constraints_hash=None):
        await self.require_project(project_id)
        if not task_prompt.strip() or len(task_prompt) > 30000 or not request_key:
            raise AppError("CANVAS_PROMPT_INVALID", "请填写提示词，且不超过 30000 个字符", 400)
        fingerprint = request_fingerprint({"step": step_id, "base": base_revision_id, "prompt": task_prompt, "sources": source_asset_ids})
        if restored_constraints_hash:
            fingerprint = request_fingerprint({"request": fingerprint, "restoredConstraintsHash": restored_constraints_hash})
        tracks = await self.recover_expired(project_id)
        track = next((t for t in tracks if t["stepId"] == step_id), None)
        if track:
            replay = next((v for v in track["revisions"] if v.get("requestKey") == request_key), None)
            if replay:
                if replay["fingerprint"] != fingerprint:
                    raise AppError("IDEMPOTENCY_KEY_CONFLICT", "该提交标识已用于不同内容", 409)
                return replay
        else:
            step = next((s for s in await self.load_steps(project_id) if s["id"] == step_id), None)
            if not step or not step["outputAssetIds"] or not step["sourceAssetIds"]:
                raise AppError("CANVAS_STEP_INCOMPLETE", "此生成记录缺少输入或输出，暂不能重新生成", 409)
            if step.get("batchStatus") and step["batchStatus"] not in {"succeeded", "failed", "partially_failed", "cancelled"}:
                raise AppError("CANVAS_ORIGINAL_RUNNING", "原批次仍在生成，请等待全部结束后再迭代", 409)
            original = {**deepcopy(step), "id": "original", "number": 1, "status": "succeeded", "createdAt": now(), "outputs": [{"assetId": asset_id, "index": i} for i, asset_id in enumerate(step["outputAssetIds"])]}
            track = {"stepId": step_id, "title": step["title"], "kind": step["kind"], "originalAssetIds": list(step["outputAssetIds"]), "currentAssetIds": list(step["outputAssetIds"]), "revisions": [original]}
        base = next((v for v in track["revisions"] if v["id"] == base_revision_id), None)
        if base is None:
            raise AppError("CANVAS_VERSION_NOT_FOUND", "提示词版本不存在，请刷新", 404)
        sources = list(source_asset_ids if source_asset_ids is not None else base["sourceAssetIds"])
        if len(sources) != len(base["sourceAssetIds"]):
            raise AppError("CANVAS_SOURCE_INVALID", "必须保留上游输入图片的数量和顺序", 400)
        for old_id, new_id in zip(base["sourceAssetIds"], sources):
            allowed = {old_id}
            for upstream in tracks:
                for index in range(len(upstream["originalAssetIds"])):
                    family = {o["assetId"] for v in upstream["revisions"] for o in v["outputs"] if o["index"] == index}
                    if old_id in family:
                        allowed.update(family)
            if new_id not in allowed:
                raise AppError("CANVAS_SOURCE_INVALID", "只能选择同一上游图片的历史版本", 409)
        frozen_sources = [await self.source_snapshot(project_id, asset_id) for asset_id in sources]
        if len(sources) > 1 and not getattr(self.editor, "supports_multiple_source_images", False):
            raise AppError("CANVAS_MULTI_SOURCE_UNSUPPORTED", "当前模型不支持此步骤需要的多张输入图片", 409)
        parameters = deepcopy(base["parameters"])
        previous_model = parameters.get("providerModel")
        connection = parameters.get("modelConnection")
        preset = parameters.get("modelPreset")
        if connection is None and self.model_connections and isinstance(preset, dict) and preset.get("connectionId"):
            connection = await self.model_connections.snapshot(preset)
        if connection is None and previous_model and previous_model != self.provider_model:
            raise AppError("CANVAS_MODEL_CHANGED", "当前服务模型与历史模型不同，请先恢复对应模型配置", 409)
        if connection is None and self.model_connections:
            # 无连接的旧任务来自环境模型，不能改用当前目录中的其他默认模型。
            connection = await self.model_connections.snapshot({"connectionId": "environment"})
        if connection is not None:
            parameters["modelConnection"] = connection
        parameters["providerModel"] = connection["modelName"] if connection else self.provider_model
        constraints = deepcopy(base["constraints"])
        if restored_constraints_hash:
            preview = await self.preview_constraints(project_id, step_id, base_revision_id)
            if preview["constraintsHash"] != restored_constraints_hash:
                raise AppError("CANVAS_CONSTRAINTS_CHANGED", "提示词预览已变化，请重新补全并确认", 409)
            constraints = preview["constraints"]
        version = {"id": str(uuid4()), "kind": track["kind"], "title": track["title"], "status": "queued", "sourceAssetIds": sources, "sourceAssets": frozen_sources, "taskPrompt": task_prompt.strip(), "constraints": constraints, "parameters": parameters, "finalPrompt": compose_prompt(track["kind"], constraints, task_prompt.strip()), "outputs": [], "createdAt": now(), "requestKey": request_key, "fingerprint": fingerprint, "baseRevisionId": base_revision_id}
        if restored_constraints_hash:
            version["restoredConstraintsHash"] = restored_constraints_hash
        version["leaseExpiresAt"] = lease_deadline()
        def append(state):
            expire_revisions(state)
            prior = next((v for v in state["revisions"] if v.get("requestKey") == request_key), None)
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise AppError("IDEMPOTENCY_KEY_CONFLICT", "该提交标识已用于不同内容", 409)
                return prior
            if any(v["status"] in {"queued", "generating"} for v in state["revisions"]):
                raise AppError("CANVAS_GENERATION_RUNNING", "此步骤正在生成，请等待完成后再提交", 409)
            version["number"] = len(state["revisions"]) + 1
            state["revisions"].append(version)
            return version
        return await self.repository.change(project_id, self.scope, step_id, track, append)

    async def select(self, project_id, step_id, output_index, asset_id):
        await self.require_project(project_id)
        await self.source_snapshot(project_id, asset_id)
        def choose(state):
            if output_index < 0 or output_index >= len(state["currentAssetIds"]) or not any(o["assetId"] == asset_id and o["index"] == output_index for v in state["revisions"] for o in v["outputs"]):
                raise AppError("CANVAS_VERSION_INVALID", "该图片不属于此位置的已完成版本", 409)
            state["currentAssetIds"][output_index] = asset_id
            return state
        return await self.repository.change(project_id, self.scope, step_id, None, choose)

    async def execute(self, project_id, step_id, revision_id):
        def claim(state):
            expire_revisions(state)
            version = next((v for v in state["revisions"] if v["id"] == revision_id), None)
            if not version or version["status"] != "queued":
                return None
            version["status"] = "generating"
            version["leaseExpiresAt"] = lease_deadline()
            return {"version": version, "count": len(state["originalAssetIds"])}
        claimed = await self.repository.change(project_id, self.scope, step_id, None, claim)
        if not claimed:
            return
        version, outputs, errors = claimed["version"], [], []
        async def heartbeat():
            while True:
                await asyncio.sleep(20)
                def renew(state):
                    record = next(v for v in state["revisions"] if v["id"] == revision_id)
                    if record["status"] == "generating":
                        record["leaseExpiresAt"] = lease_deadline()
                await self.repository.change(project_id, self.scope, step_id, None, renew)
        heartbeat_task = asyncio.create_task(heartbeat())
        interrupted = False
        try:
            project = await self.require_project(project_id)
            inputs = []
            for snapshot in version["sourceAssets"]:
                current = await self.source_snapshot(project_id, snapshot["assetId"])
                obj = await self.projects.get_object(UUID(snapshot["objectId"]), self.scope)
                stored = await self.storage.get(obj.storage_key) if obj else None
                if current != snapshot or not stored or sha256(stored.data).hexdigest() != snapshot["sha256"]:
                    raise AppError("CANVAS_SOURCE_CHANGED", "上游图片内容与提交时的记录不一致", 409)
                inputs.append(ImageEditInput(stored.data, snapshot["mimeType"], snapshot["filename"]))
            params = version["parameters"]
            request = ImageEditRequest(version["finalPrompt"], inputs[0].image_bytes, inputs[0].image_mime_type, inputs[0].image_filename, str(params.get("aspectRatio") or params.get("ratio") or "1:1"), str(params.get("resolution") or params.get("size") or "标准 1K"), tuple(inputs), model_connection=params.get("modelConnection"))
            for index in range(claimed["count"]):
                created = None
                try:
                    def require_live(state):
                        expire_revisions(state)
                        record = next(v for v in state["revisions"] if v["id"] == revision_id)
                        return record["status"] == "generating"
                    if not await self.repository.change(project_id, self.scope, step_id, None, require_live):
                        break
                    result = await self.editor.edit(request)
                    filename = f"{version['title']}-V{version['number']}-{index + 1}.png"
                    if version["kind"] == "white":
                        created = await self.assets.upload_asset(project_id, "white_background", result.image_bytes, result.image_mime_type, filename, source_asset_id=UUID(version["sourceAssetIds"][0]), source_kind="generated", source_snapshot={"canvasRevisionId": revision_id, "canvasStepId": step_id})
                    else:
                        created = await self.assets.create_generated_asset(project_id, result.image_bytes, result.image_mime_type, filename, source_asset_id=UUID(version["sourceAssetIds"][0]), generation_snapshot_id=UUID(revision_id))
                    raw_module = params.get("module") if isinstance(params.get("module"), dict) else None
                    module_snapshot = raw_module or {"id": version["kind"], "label": version["title"], "mode": "hero" if version["kind"] == "hero" else "detail"}
                    await self.archive.archive_project_output(project_id=project_id, project_name=project.name, product_type={"white": "white_background", "hero": "hero", "suite": "detail", "detail": "detail"}.get(version["kind"], "edit"), source_version_id=created.id, preview_url=f"/api/projects/{project_id}/assets/{created.id}/preview", source_snapshot={"assetId": str(created.id), "canvasStepId": step_id, "canvasRevisionId": revision_id, "batchId": revision_id, "batchCreatedAt": version.get("createdAt"), "creationMode": params.get("creationMode"), "moduleId": module_snapshot.get("id"), "module": module_snapshot}, prompt_snapshot={"finalPrompt": version["finalPrompt"], "taskPrompt": version["taskPrompt"], "constraints": version["constraints"]}, config_snapshot=params)
                    outputs.append({"assetId": str(created.id), "index": index})
                    # 每张图独立保存，后续中断不会丢失已完成版本。
                    def checkpoint(state):
                        record = next(v for v in state["revisions"] if v["id"] == revision_id)
                        if record["status"] != "generating":
                            raise AppError("CANVAS_LEASE_EXPIRED", "生成任务已中断，请重新提交", 409)
                        record["outputs"] = deepcopy(outputs)
                        state["currentAssetIds"][index] = str(created.id)
                    await self.repository.change(project_id, self.scope, step_id, None, checkpoint)
                except Exception:
                    outputs = [output for output in outputs if not created or output["assetId"] != str(created.id)]
                    if created:
                        with suppress(Exception):
                            await self.assets.delete_asset(project_id, created.id)
                    errors.append({"index": index, "message": "生成或保存失败，请重新提交此版本"})
        except asyncio.CancelledError:
            interrupted = True
            errors.append({"index": -1, "message": "生成任务已中断，已保存图片保留；请确认后重新生成"})
        except Exception:
            errors.append({"index": -1, "message": "生成未完成，请检查上游图片和模型服务后重新提交"})
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await heartbeat_task
        def complete(state):
            record = next(v for v in state["revisions"] if v["id"] == revision_id)
            if record["status"] != "generating":
                return record
            record.update(outputs=outputs, errors=errors, status="partial" if outputs and errors else "failed" if errors else "succeeded")
            for output in outputs:
                state["currentAssetIds"][output["index"]] = output["assetId"]
            return record
        await self.repository.change(project_id, self.scope, step_id, None, complete)
        if interrupted:
            raise asyncio.CancelledError()
