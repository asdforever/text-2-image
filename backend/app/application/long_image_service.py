"""长图资产保存、来源追溯和项目成品归档。"""
import asyncio
from hashlib import sha256
from uuid import UUID, uuid5, NAMESPACE_URL

from starlette.concurrency import run_in_threadpool

from ..core.errors import AppError
from .idempotency import request_fingerprint
from .long_image_rendering import MAX_INPUT_BYTES, render_long_image, slice_long_image


class LongImageService:
    def __init__(self, assets, archive, idempotency):
        self.assets, self.archive, self.idempotency = assets, archive, idempotency
        self.repository = assets.repository
        self.lock = asyncio.Lock()

    @property
    def workspace(self):
        return self.assets.identity_provider.get_context().workspace_id

    async def require_project(self, project_id):
        project = await self.repository.get_project(project_id, self.workspace)
        if project is None or project.status != "active":
            raise AppError("LONG_IMAGE_PROJECT_NOT_FOUND", "项目不存在或已归档", 404)
        return project

    async def view(self, project_id, asset):
        _, obj = await self.assets.get_asset_details(project_id, asset.id)
        return {"assetId": str(asset.id), "title": asset.source_snapshot["recipe"]["title"], "width": obj.width, "height": obj.height,
                "previewUrl": f"/api/projects/{project_id}/assets/{asset.id}/preview", "recipe": asset.source_snapshot["recipe"]}

    async def list(self, project_id):
        await self.require_project(project_id)
        return [await self.view(project_id, asset) for asset in await self.assets.list_assets(project_id)
                if asset.source_kind == "long_image" and asset.state == "available"]

    async def archive_asset(self, project, asset):
        # 归档服务依据来源资产幂等，归档中断后可用同一请求恢复。
        try:
            if self.assets.project_archive:
                await self.assets.project_archive.link_project_asset(project, asset)
            await self.archive.archive_project_output(
                project_id=project.id, project_name=project.name, product_type="detail", source_version_id=asset.id,
                preview_url=f"/api/projects/{project.id}/assets/{asset.id}/preview",
                source_snapshot={**asset.source_snapshot, "projectAssetId": str(asset.id), "kind": "long_image"},
                config_snapshot=asset.source_snapshot["recipe"],
            )
        except Exception as exc:
            raise AppError("LONG_IMAGE_ARCHIVE_FAILED", "长图已保存，成品归档暂未完成，请重试保存恢复归档", 503) from exc

    async def save(self, project_id, recipe, request_key):
        project = await self.require_project(project_id)
        payload = recipe.model_dump(mode="json")
        scope = f"{self.workspace}:long-image:{project_id}"
        fingerprint = request_fingerprint(payload)
        operation_id = str(uuid5(NAMESPACE_URL, scope + ":" + request_key))
        async with self.lock:
            existing_record = await self.idempotency.get(scope, request_key)
            if existing_record and existing_record.request_fingerprint != fingerprint:
                raise AppError("IDEMPOTENCY_KEY_CONFLICT", "此保存标识已用于另一份长图方案", 409)
            existing = next((asset for asset in await self.assets.list_assets(project_id)
                             if asset.source_kind == "long_image" and asset.source_snapshot.get("operationId") == operation_id and asset.state == "available"), None)
            if existing:
                if existing.source_snapshot.get("requestFingerprint") != fingerprint:
                    raise AppError("IDEMPOTENCY_KEY_CONFLICT", "此保存标识已用于另一份长图方案", 409)
                await self.archive_asset(project, existing)
                result = await self.view(project_id, existing)
                await self.idempotency.complete(scope, request_key, fingerprint, response_status=201, response_body=result, resource_id=existing.id)
                return result
            if existing_record and existing_record.status != "failed":
                raise AppError("LONG_IMAGE_SAVE_UNAVAILABLE", "此前保存未完成或结果已删除，请重新打开制作器再保存", 409)
            bodies, sources = [], []
            total_bytes = 0
            for item in recipe.items:
                try:
                    asset, obj = await self.assets.get_asset_details(project_id, item.assetId)
                except AppError as exc:
                    raise AppError("LONG_IMAGE_SOURCE_UNAVAILABLE", "来源图片不存在、已删除或不属于此项目，请替换后保存", 409) from exc
                if asset.state != "available":
                    raise AppError("LONG_IMAGE_SOURCE_UNAVAILABLE", "来源图片已删除或不可用，请替换后保存", 409)
                if obj.width * obj.height > 24_000_000:
                    raise AppError("LONG_IMAGE_SOURCE_LIMIT", "单张来源图片超过 2400 万像素，请先缩小图片", 400)
                total_bytes += obj.byte_size
                if total_bytes > MAX_INPUT_BYTES:
                    raise AppError("LONG_IMAGE_INPUT_LIMIT", "来源图片合计超过 100 MiB，请减少图片", 400)
                stored = await self.assets.get_preview(project_id, item.assetId)
                if sha256(stored.data).hexdigest() != obj.sha256:
                    raise AppError("LONG_IMAGE_SOURCE_CHANGED", "来源图片内容校验失败，请重新选择图片", 409)
                bodies.append(stored.data)
                sources.append({"assetId": str(asset.id), "objectId": str(obj.id), "sha256": obj.sha256, "filename": obj.original_filename})
            body, _, _ = await run_in_threadpool(render_long_image, recipe, bodies)
            claim = await self.idempotency.claim(scope, request_key, fingerprint, retry_failed=True)
            if not claim.is_owner:
                raise AppError("IDEMPOTENCY_IN_PROGRESS", "此长图正在保存，请稍后重试", 409)
            snapshot = {"schemaVersion": 1, "recipe": payload, "sources": sources, "operationId": operation_id, "requestFingerprint": fingerprint}
            try:
                asset = await self.assets.create_generated_asset(
                    project_id, body, "image/png", recipe.title + ".png", source_asset_id=recipe.items[0].assetId,
                    generation_snapshot_id=UUID(operation_id), source_kind="long_image", source_snapshot=snapshot,
                    max_output_bytes=128 * 1024 * 1024,
                )
            except Exception as exc:
                await self.idempotency.fail(scope, request_key, fingerprint, response_status=503, response_body={"message": "长图资产写入失败，可重试"})
                raise AppError("LONG_IMAGE_SAVE_FAILED", "长图保存暂未完成，请重试；若仍失败请重新打开制作器", 503) from exc
            await self.archive_asset(project, asset)
            result = await self.view(project_id, asset)
            await self.idempotency.complete(scope, request_key, fingerprint, response_status=201, response_body=result, resource_id=asset.id)
            return result

    async def download(self, project_id, asset_id, slice_height):
        await self.require_project(project_id)
        asset, _ = await self.assets.get_asset_details(project_id, asset_id)
        if asset.state != "available" or asset.source_kind != "long_image":
            raise AppError("LONG_IMAGE_NOT_FOUND", "长图不存在或已删除", 404)
        stored = await self.assets.get_preview(project_id, asset_id)
        if slice_height is None:
            return stored.data, "image/png", "long-image.png"
        async with self.lock:
            body = await run_in_threadpool(slice_long_image, stored.data, slice_height)
        return body, "application/zip", "long-image-slices.zip"
