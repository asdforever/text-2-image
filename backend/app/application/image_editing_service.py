"""图片编辑会话应用服务。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
from uuid import UUID

from ..core.errors import AppError
from ..core.identity import IdentityProvider
from .image_editing_rendering import validate_operations
from ..image_editing_repository import InMemoryImageEditingRepository, ImageEditRevisionConflict, ImageEditSessionRecord, ImageEditTaskRecord


@dataclass
class ImageOcrResultRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    session_id: UUID
    source_version_id: UUID
    request_fingerprint: str
    text: str = ""
    regions: list[dict[str, Any]] = field(default_factory=list)
    provider_snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DefaultOcrProvider:
    async def recognize(self, source_snapshot: dict[str, Any]) -> dict[str, Any]:
        return {"text": "", "regions": []}


class ImageEditingService:
    def __init__(
        self,
        repository: Any | None,
        project_repository: Any,
        identity_provider: IdentityProvider,
        ocr_provider: Any | None = None,
        model_connections: Any | None = None,
    ) -> None:
        self.repository = repository or InMemoryImageEditingRepository()
        self.project_repository = project_repository
        self.identity_provider = identity_provider
        self.ocr_provider = ocr_provider or DefaultOcrProvider()
        self.model_connections = model_connections

    def _workspace_id(self) -> UUID:
        return self.identity_provider.get_context().workspace_id

    async def create_session(
        self,
        project_id: UUID,
        source_version_id: UUID,
    ) -> ImageEditSessionRecord:
        workspace_id = self._workspace_id()
        project = await self.project_repository.get_project(project_id, workspace_id)
        if project is None:
            raise AppError("IMAGE_EDIT_PROJECT_NOT_FOUND", "项目不存在或不属于当前工作区", 404)

        source = await self.project_repository.get_asset(source_version_id, workspace_id)
        if source is None or source.project_id != project_id or source.state != "available":
            raise AppError("IMAGE_EDIT_SOURCE_SCOPE", "源图片版本不属于当前项目", 409)
        object_record = await self.project_repository.get_object(source.object_id, workspace_id)
        if object_record is None or object_record.state != "available":
            raise AppError("IMAGE_EDIT_SOURCE_SCOPE", "源图片版本不可用", 409)

        source_snapshot = {
            "assetId": str(source.id),
            "objectId": str(source.object_id),
            "projectId": str(source.project_id),
            "kind": source.kind,
            "filename": object_record.original_filename,
            "mimeType": object_record.media_type,
            "byteSize": object_record.byte_size,
            "width": object_record.width,
            "height": object_record.height,
            "sha256": object_record.sha256,
        }
        return await self.repository.create_session(
            workspace_id, project_id, source_version_id, source_snapshot
        )

    async def get_session(self, session_id: UUID) -> ImageEditSessionRecord | None:
        return await self.repository.get_session(session_id, self._workspace_id())

    async def list_sessions(
        self, project_id: UUID, *, include_archived: bool = False
    ) -> list[ImageEditSessionRecord]:
        if await self.project_repository.get_project(project_id, self._workspace_id()) is None:
            raise AppError("IMAGE_EDIT_PROJECT_NOT_FOUND", "项目不存在或不属于当前工作区", 404)
        return await self.repository.list_sessions(
            project_id, self._workspace_id(), include_archived=include_archived
        )

    async def _require_session(self, session_id: UUID) -> ImageEditSessionRecord:
        session = await self.get_session(session_id)
        if session is None:
            raise AppError("IMAGE_EDIT_SESSION_NOT_FOUND", "图片编辑会话不存在", 404)
        if session.status != "draft":
            raise AppError("IMAGE_EDIT_SESSION_LOCKED", "当前会话已提交，不能修改草稿", 409)
        return session

    async def add_operation(
        self, session_id: UUID, operation: dict[str, Any], *, expected_revision: int
    ) -> ImageEditSessionRecord:
        await self._require_session(session_id)
        if isinstance(operation.get("payload"), dict) and operation["payload"].get("schemaVersion") == 2:
            validate_operations([operation])
        try:
            return await self.repository.save_operation(
                session_id, self._workspace_id(), operation, expected_revision
            )
        except ImageEditRevisionConflict as conflict:
            raise AppError(
                "IMAGE_EDIT_REVISION_CONFLICT",
                "编辑会话已更新，请刷新后重试",
                409,
            ) from conflict

    async def update_operation(
        self,
        session_id: UUID,
        operation_id: str,
        operation: dict[str, Any],
        *,
        expected_revision: int,
    ) -> ImageEditSessionRecord:
        payload = dict(operation)
        payload["operationId"] = operation_id
        return await self.add_operation(session_id, payload, expected_revision=expected_revision)

    async def remove_operation(
        self, session_id: UUID, operation_id: str, *, expected_revision: int
    ) -> ImageEditSessionRecord:
        await self._require_session(session_id)
        try:
            return await self.repository.remove_operation(
                session_id, self._workspace_id(), operation_id, expected_revision
            )
        except ImageEditRevisionConflict as conflict:
            raise AppError(
                "IMAGE_EDIT_REVISION_CONFLICT",
                "编辑会话已更新，请刷新后重试",
                409,
            ) from conflict

    async def recognize_ocr(
        self,
        session_id: UUID,
        source_version_id: UUID,
        *,
        idempotency_key: str | None = None,
    ) -> ImageOcrResultRecord:
        session = await self.get_session(session_id)
        if session is None:
            raise AppError("IMAGE_EDIT_SESSION_NOT_FOUND", "图片编辑会话不存在", 404)
        workspace_id = self._workspace_id()
        source = await self.project_repository.get_asset(source_version_id, workspace_id)
        if source is None or source.project_id != session.project_id or source.state != "available":
            raise AppError("IMAGE_EDIT_SOURCE_SCOPE", "OCR 源图片版本不属于当前项目", 409)
        fingerprint = hashlib.sha256(
            json.dumps({"sourceVersionId": str(source_version_id), "key": idempotency_key or ""}, sort_keys=True).encode()
        ).hexdigest()
        cached = await self.repository.get_ocr_result(session_id, source_version_id, fingerprint)
        if cached is not None:
            return cached
        result = await self.ocr_provider.recognize(session.source_snapshot | {"assetId": str(source_version_id)})
        record = ImageOcrResultRecord(
            id=__import__("uuid").uuid4(),
            workspace_id=workspace_id,
            project_id=session.project_id,
            session_id=session.id,
            source_version_id=source_version_id,
            request_fingerprint=fingerprint,
            text=str(result.get("text", "")),
            regions=list(result.get("regions", []) or []),
            provider_snapshot={"provider": type(self.ocr_provider).__name__},
        )
        return await self.repository.save_ocr_result(record)

    async def submit_session(
        self,
        session_id: UUID,
        *,
        prompt_snapshot: dict[str, Any],
        config_snapshot: dict[str, Any],
        idempotency_key: str | None = None,
        regenerate_summary: str | None = None,
    ) -> ImageEditTaskRecord:
        session = await self.get_session(session_id)
        if session is None:
            raise AppError("IMAGE_EDIT_SESSION_NOT_FOUND", "图片编辑会话不存在", 404)
        if not session.operations_snapshot and not (regenerate_summary or str(prompt_snapshot.get("summary", "")).strip()):
            raise AppError("IMAGE_EDIT_EMPTY_DRAFT", "没有可提交的编辑操作或生成说明", 400)
        modern = any(item.get("payload", {}).get("schemaVersion") == 2 for item in session.operations_snapshot)
        if modern:
            validate_operations(session.operations_snapshot)
        local_only = modern and all(item.get("type") == "crop_resize" for item in session.operations_snapshot)
        if self.model_connections is not None and not local_only:
            parameters = config_snapshot.get("generationParams")
            parameters = parameters if isinstance(parameters, dict) else config_snapshot
            from .model_connection_service import model_selection_id, validate_model_dimensions
            connection = await self.model_connections.snapshot(model_selection_id(parameters.get("modelId") or config_snapshot.get("modelId")))
            validate_model_dimensions(connection, parameters.get("ratio") or parameters.get("aspectRatio") or "1:1",
                                      parameters.get("size") or parameters.get("resolution") or "标准 1K")
            config_snapshot = {**config_snapshot, "modelConnection": connection, "providerModel": connection["modelName"]}
        return await self.repository.create_task(
            session,
            prompt_snapshot | ({"summary": regenerate_summary} if regenerate_summary else {}),
            config_snapshot,
            idempotency_key,
        )

    async def retry_attempt(self, attempt_id: UUID) -> ImageEditTaskRecord:
        task = await self.repository.retry_attempt(attempt_id, self._workspace_id())
        if task is None:
            raise AppError("IMAGE_EDIT_ATTEMPT_NOT_FOUND", "生成尝试不存在", 404)
        if not any(item.id == attempt_id and item.status == "failed" for item in task.attempts):
            raise AppError("IMAGE_EDIT_ATTEMPT_NOT_RETRYABLE", "当前生成尝试不可重试", 409)
        return task

    async def regenerate_task(self, task_id: UUID, summary: str | None = None) -> ImageEditTaskRecord:
        task = await self.repository.get_task(task_id, self._workspace_id())
        if task is None:
            raise AppError("IMAGE_EDIT_TASK_NOT_FOUND", "图片编辑任务不存在", 404)
        return await self.repository.create_task(
            type("SessionSnapshot", (), {
                "id": task.session_id,
                "workspace_id": task.workspace_id,
                "project_id": task.project_id,
                "source_snapshot": task.source_snapshot,
                "operations_snapshot": task.operations_snapshot,
            })(),
            task.prompt_snapshot | ({"summary": summary} if summary else {}),
            task.config_snapshot,
            None,
        )

    async def select_version(self, task_id: UUID, version_id: UUID, selection: str = "current") -> Any:
        if selection not in {"current", "final"}:
            raise AppError("IMAGE_EDIT_SELECTION_INVALID", "版本选择类型无效", 400)
        try:
            version = await self.repository.select_version(task_id, version_id, self._workspace_id(), selection)
        except ValueError as exc:
            raise AppError("IMAGE_EDIT_VERSION_NOT_READY", "只能选择已完成的图片版本", 409) from exc
        if version is None:
            raise AppError("IMAGE_EDIT_VERSION_NOT_FOUND", "图片版本不存在", 404)
        return version

    async def archive_session(self, session_id: UUID) -> ImageEditSessionRecord:
        session = await self.repository.archive_session(session_id, self._workspace_id())
        if session is None:
            raise AppError("IMAGE_EDIT_SESSION_NOT_FOUND", "图片编辑会话不存在", 404)
        return session
