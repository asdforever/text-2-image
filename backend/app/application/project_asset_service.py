from typing import Any
from uuid import UUID, uuid4

from ..core.errors import AppError
from ..core.identity import IdentityProvider
from ..project_repository import AssetObjectRecord, ProjectAssetRecord
from ..project_storage import inspect_project_image, project_asset_object_key
from ..storage import StoredObject
from .idempotency import IdempotencyClaim, request_fingerprint
from .ports import IdempotencyStore, MemoryIdempotencyStore


class ProjectAssetService:
    """协调项目图片资产、对象存储与当前选择。"""

    def __init__(
        self,
        repository: Any,
        storage: Any,
        identity_provider: IdentityProvider,
        *,
        max_upload_bytes: int = 12 * 1024 * 1024,
        idempotency_store: IdempotencyStore | None = None,
        project_archive: Any | None = None,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.identity_provider = identity_provider
        self.max_upload_bytes = max_upload_bytes
        self.idempotency_store = idempotency_store or MemoryIdempotencyStore()
        self.project_archive = project_archive

    async def upload_asset(
        self,
        project_id: UUID,
        kind: str,
        body: bytes,
        declared_mime: str | None,
        filename: str,
        *,
        source_asset_id: UUID | None = None,
        idempotency_key: str | None = None,
        source_kind: str = "upload",
        source_library_id: str | None = None,
        source_resource_id: str | None = None,
        source_resource_version_id: str | None = None,
        source_snapshot: dict[str, Any] | None = None,
    ) -> ProjectAssetRecord:
        context = self.identity_provider.get_context()
        project = await self.repository.get_project(project_id, context.workspace_id)
        if project is None:
            raise AppError("INVALID_PROJECT_ID", "project does not exist", 404)
        if kind not in {"source", "white_background"}:
            raise AppError("INVALID_PROJECT_ASSET_KIND", "asset kind is not uploadable", 400)
        if kind == "white_background" and source_asset_id is not None:
            source = (
                await self.repository.get_asset(source_asset_id, context.workspace_id)
                if source_asset_id else None
            )
            if source is None or source.project_id != project_id:
                raise AppError("INVALID_SOURCE_ASSET", "source asset does not belong to project", 400)
        elif source_asset_id is not None:
            raise AppError("INVALID_SOURCE_ASSET", "source images cannot have a source asset", 400)

        media_type, width, height, sha256 = inspect_project_image(
            body, declared_mime, self.max_upload_bytes
        )
        scope = f"{context.workspace_id}:POST:/api/projects/{project_id}/assets"
        fingerprint = request_fingerprint(
            {
                "kind": kind,
                "sourceAssetId": str(source_asset_id) if source_asset_id else None,
                "sha256": sha256,
                "filename": filename.strip() if filename else "upload",
            }
        )
        if idempotency_key:
            claim = await self.idempotency_store.claim(scope, idempotency_key, fingerprint)
            if not claim.is_owner:
                return await self._replay_asset(claim, project_id, context.workspace_id)
        object_id = uuid4()
        key = project_asset_object_key(context.workspace_id, project_id, object_id, media_type)
        resolved_filename = filename.strip() if filename and filename.strip() else "upload"
        await self.storage.put(StoredObject(key, body, media_type))
        try:
            object_record = await self.repository.create_object(
                context.workspace_id,
                key,
                resolved_filename,
                media_type,
                len(body),
                width,
                height,
                sha256,
                object_id=object_id,
            )
            asset = await self.repository.create_asset(
                project_id, object_record.id, kind, source_asset_id=source_asset_id,
                source_kind=source_kind, source_library_id=source_library_id,
                source_resource_id=source_resource_id, source_resource_version_id=source_resource_version_id,
                source_snapshot=source_snapshot,
            )
        except Exception as exc:
            await self.storage.delete(key)
            if idempotency_key:
                await self._record_failure(scope, idempotency_key, fingerprint, exc)
            raise
        try:
            await self._link_project_asset(project, asset)
            if idempotency_key:
                await self.idempotency_store.complete(
                    scope,
                    idempotency_key,
                    fingerprint,
                    response_status=201,
                    response_body={"id": str(asset.id)},
                    resource_id=asset.id,
                )
            return asset
        except Exception as exc:
            if idempotency_key:
                await self._record_failure(scope, idempotency_key, fingerprint, exc)
            raise

    async def create_generated_asset(
        self,
        project_id: UUID,
        body: bytes,
        declared_mime: str | None,
        filename: str,
        *,
        source_asset_id: UUID,
        generation_snapshot_id: UUID,
        source_kind: str = "upload",
        source_snapshot: dict[str, Any] | None = None,
        max_output_bytes: int | None = None,
    ) -> ProjectAssetRecord:
        context = self.identity_provider.get_context()
        project = await self.repository.get_project(project_id, context.workspace_id)
        source = await self.repository.get_asset(source_asset_id, context.workspace_id)
        if project is None:
            raise AppError("INVALID_PROJECT_ID", "project does not exist", 404)
        if source is None or source.project_id != project_id:
            raise AppError("INVALID_SOURCE_ASSET", "source asset does not belong to project", 400)
        media_type, width, height, sha256 = inspect_project_image(
            body, declared_mime, max_output_bytes or self.max_upload_bytes
        )
        object_id = uuid4()
        key = project_asset_object_key(
            context.workspace_id, project_id, object_id, media_type
        )
        resolved_filename = filename.strip() if filename and filename.strip() else "generated"
        await self.storage.put(StoredObject(key, body, media_type))
        object_record = None
        try:
            object_record = await self.repository.create_object(
                context.workspace_id,
                key,
                resolved_filename,
                media_type,
                len(body),
                width,
                height,
                sha256,
                object_id=object_id,
            )
            asset = await self.repository.create_asset(
                project_id,
                object_record.id,
                "generated",
                source_asset_id=source_asset_id,
                generation_snapshot_id=generation_snapshot_id,
                source_kind=source_kind,
                source_snapshot=source_snapshot,
            )
        except Exception:
            try:
                await self.storage.delete(key)
            except Exception:
                if object_record is not None:
                    await self.repository.set_object_state(
                        object_record.id, context.workspace_id, "cleanup_pending"
                    )
            else:
                if object_record is not None:
                    await self.repository.set_object_state(
                        object_record.id, context.workspace_id, "cleaned"
                    )
            raise
        await self._link_project_asset(project, asset)
        return asset

    async def list_assets(self, project_id: UUID) -> list[ProjectAssetRecord]:
        context = self.identity_provider.get_context()
        return await self.repository.list_assets(project_id, context.workspace_id)

    async def get_asset_details(
        self, project_id: UUID, asset_id: UUID
    ) -> tuple[ProjectAssetRecord, AssetObjectRecord]:
        context = self.identity_provider.get_context()
        asset = await self.repository.get_asset(asset_id, context.workspace_id)
        if asset is None or asset.project_id != project_id:
            raise AppError("INVALID_PROJECT_ASSET_ID", "project asset does not exist", 404)
        object_record = await self.repository.get_object(asset.object_id, context.workspace_id)
        if object_record is None or object_record.state != "available":
            raise AppError("OBJECT_NOT_FOUND", "project asset preview does not exist", 404)
        return asset, object_record

    async def list_asset_details(self, project_id: UUID) -> list[tuple[ProjectAssetRecord, AssetObjectRecord]]:
        context = self.identity_provider.get_context()
        details = await self.repository.list_asset_details(project_id, context.workspace_id)
        result = []
        for asset, object_record in details:
            # Preserve the individual-read error contract instead of silently losing broken assets.
            if object_record is None or object_record.state != "available":
                raise AppError("OBJECT_NOT_FOUND", "project asset preview does not exist", 404)
            result.append((asset, object_record))
        return result

    async def get_preview(self, project_id: UUID, asset_id: UUID) -> StoredObject:
        _, object_record = await self.get_asset_details(project_id, asset_id)
        stored = await self.storage.get(object_record.storage_key)
        if stored is None:
            raise AppError("OBJECT_NOT_FOUND", "project asset preview does not exist", 404)
        return stored

    async def select_asset(
        self, project_id: UUID, role: str, asset_id: UUID
    ) -> ProjectAssetRecord:
        context = self.identity_provider.get_context()
        if role not in {"source", "white_background", "generated"}:
            raise AppError("INVALID_PROJECT_ASSET_ROLE", "asset role is invalid", 400)
        selected = await self.repository.select_asset(
            project_id, role, asset_id, context.workspace_id
        )
        if selected is None:
            raise AppError("INVALID_PROJECT_ASSET_ID", "project asset does not match role", 404)
        return selected

    async def clear_selection(self, project_id: UUID, role: str) -> bool:
        context = self.identity_provider.get_context()
        if role not in {"source", "white_background", "generated"}:
            raise AppError("INVALID_PROJECT_ASSET_ROLE", "asset role is invalid", 400)
        return await self.repository.clear_selection(project_id, role, context.workspace_id)

    async def delete_asset(self, project_id: UUID, asset_id: UUID) -> ProjectAssetRecord:
        context = self.identity_provider.get_context()
        asset, object_record = await self.get_asset_details(project_id, asset_id)
        deleted = await self.repository.delete_asset(asset.id, context.workspace_id)
        if deleted is None:
            raise AppError("INVALID_PROJECT_ASSET_ID", "project asset does not exist", 404)
        if self.project_archive is not None:
            await self.project_archive.unlink_project_asset(project_id, asset.id)
        if await self.repository.object_reference_count(object_record.id):
            return deleted
        try:
            await self.storage.delete(object_record.storage_key)
        except Exception:
            await self.repository.set_object_state(
                object_record.id, context.workspace_id, "cleanup_pending"
            )
        else:
            await self.repository.set_object_state(object_record.id, context.workspace_id, "cleaned")
        return deleted

    async def retry_object_cleanup(self, object_id: UUID) -> bool:
        context = self.identity_provider.get_context()
        object_record = await self.repository.get_object(object_id, context.workspace_id)
        if object_record is None or object_record.state != "cleanup_pending":
            return False
        if await self.repository.object_reference_count(object_id):
            return False
        try:
            await self.storage.delete(object_record.storage_key)
        except Exception:
            await self.repository.set_object_state(object_id, context.workspace_id, "cleanup_pending")
            return False
        await self.repository.set_object_state(object_id, context.workspace_id, "cleaned")
        return True

    async def retry_asset_cleanup(self, project_id: UUID, asset_id: UUID) -> bool:
        context = self.identity_provider.get_context()
        asset = await self.repository.get_asset(asset_id, context.workspace_id)
        if asset is None or asset.project_id != project_id:
            raise AppError("INVALID_PROJECT_ASSET_ID", "project asset does not exist", 404)
        return await self.retry_object_cleanup(asset.object_id)

    async def delete_project_assets(self, project_id: UUID) -> None:
        context = self.identity_provider.get_context()
        pending = await self.repository.list_assets(project_id, context.workspace_id)
        while pending:
            source_ids = {asset.source_asset_id for asset in pending if asset.source_asset_id}
            leaves = [asset for asset in pending if asset.id not in source_ids]
            if not leaves:
                raise AppError("INVALID_PROJECT_ASSET_GRAPH", "project assets have a cyclic source relationship", 409)
            for asset in leaves:
                await self.delete_asset(project_id, asset.id)
            pending = await self.repository.list_assets(project_id, context.workspace_id)

    async def get_selections(self, project_id: UUID) -> dict[str, UUID]:
        context = self.identity_provider.get_context()
        return await self.repository.get_selections(project_id, context.workspace_id)

    async def _link_project_asset(self, project: Any, asset: ProjectAssetRecord) -> None:
        if self.project_archive is not None:
            await self.project_archive.link_project_asset(project, asset)

    async def _replay_asset(
        self, claim: IdempotencyClaim, project_id: UUID, workspace_id: UUID
    ) -> ProjectAssetRecord:
        if claim.record.status == "in_progress":
            raise AppError("IDEMPOTENCY_IN_PROGRESS", "an equivalent request is already in progress", 409)
        if claim.record.status == "failed":
            body = claim.record.response_body or {}
            raise AppError(
                str(body.get("code", "IDEMPOTENCY_PREVIOUSLY_FAILED")),
                str(body.get("message", "the original request failed")),
                claim.record.response_status or 409,
            )
        asset = (
            await self.repository.get_asset(claim.record.resource_id, workspace_id)
            if claim.record.resource_id
            else None
        )
        if asset is None or asset.project_id != project_id:
            raise AppError("IDEMPOTENCY_RESOURCE_MISSING", "the original idempotent resource no longer exists", 409)
        return asset

    async def _record_failure(
        self, scope: str, key: str, fingerprint: str, exc: Exception
    ) -> None:
        code = exc.code if isinstance(exc, AppError) else "DEPENDENCY_FAILURE"
        message = exc.message if isinstance(exc, AppError) else "request dependency failed"
        status = exc.status_code if isinstance(exc, AppError) else 503
        try:
            await self.idempotency_store.fail(
                scope,
                key,
                fingerprint,
                response_status=status,
                response_body={"code": code, "message": message},
            )
        except Exception:
            pass
