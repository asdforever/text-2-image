from uuid import UUID, uuid4

from ..core.identity import IdentityProvider
from ..core.errors import AppError
from ..image_processing import inspect_image, thumbnail_bytes
from ..repository import ImageRecord, SuiteRecord
from ..storage import StoredObject
from .idempotency import IdempotencyClaim, request_fingerprint
from .ports import Clock, IdempotencyStore, ObjectStoragePort, SuiteRepository


class SuiteService:
    """协调 suite 与 input-image 用例的应用服务。"""

    def __init__(
        self,
        repository: SuiteRepository,
        storage: ObjectStoragePort,
        clock: Clock,
        identity_provider: IdentityProvider,
        idempotency_store: IdempotencyStore,
        max_upload_bytes: int = 12 * 1024 * 1024,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.clock = clock
        self.identity_provider = identity_provider
        self.idempotency_store = idempotency_store
        self.max_upload_bytes = max_upload_bytes

    async def create_suite(self, name: str, idempotency_key: str | None = None) -> SuiteRecord:
        context = self.identity_provider.get_context()
        if not idempotency_key:
            return await self.repository.create_suite(name, context.workspace_id)

        scope = f"{context.workspace_id}:POST:/api/suites"
        fingerprint = request_fingerprint({"name": name})
        claim = await self.idempotency_store.claim(scope, idempotency_key, fingerprint)
        if not claim.is_owner:
            return await self._replay_suite(claim, context.workspace_id)
        try:
            suite = await self.repository.create_suite(name, context.workspace_id)
            await self.idempotency_store.complete(
                scope,
                idempotency_key,
                fingerprint,
                response_status=201,
                response_body=self._suite_snapshot(suite),
                resource_id=suite.id,
            )
            return suite
        except Exception as exc:
            await self._record_failure(scope, idempotency_key, fingerprint, exc)
            raise

    async def list_suites(self) -> list[SuiteRecord]:
        context = self.identity_provider.get_context()
        return await self.repository.list_suites(context.workspace_id)

    async def get_suite(self, suite_id: UUID) -> SuiteRecord | None:
        context = self.identity_provider.get_context()
        return await self.repository.get_suite(suite_id, context.workspace_id)

    async def upload_input_image(
        self,
        suite_id: UUID,
        body: bytes,
        declared_mime: str | None,
        filename: str,
        ordinal: int | None = None,
        idempotency_key: str | None = None,
    ) -> ImageRecord:
        suite = await self.get_suite(suite_id)
        if suite is None:
            raise AppError("INVALID_SUITE_ID", "suite does not exist", 404)

        mime_type, width, height, digest = inspect_image(
            body, declared_mime, self.max_upload_bytes
        )
        context = self.identity_provider.get_context()
        scope = f"{context.workspace_id}:POST:/api/suites/{suite_id}/input-images"
        fingerprint = request_fingerprint(
            {
                "sha256": digest,
                "declaredMime": declared_mime,
                "filename": filename or "upload",
                "ordinal": ordinal,
            }
        )
        if idempotency_key:
            claim = await self.idempotency_store.claim(
                scope, idempotency_key, fingerprint
            )
            if not claim.is_owner:
                return self._replay_image(claim, suite)

        resolved_ordinal = ordinal
        if resolved_ordinal is None:
            resolved_ordinal = max((item.ordinal for item in suite.images), default=0) + 1
        if not 1 <= resolved_ordinal <= 6:
            raise AppError("INVALID_ORDINAL", "ordinal must be between 1 and 6", 400)

        image_id = uuid4()
        prefix = f"suites/{suite_id}/inputs/{image_id}"
        original_key = f"{prefix}/original"
        thumbnail_key = f"{prefix}/thumbnail"
        record = ImageRecord(
            image_id,
            suite_id,
            resolved_ordinal,
            original_key,
            thumbnail_key,
            digest,
            width,
            height,
            mime_type,
            filename or "upload",
            self.clock.now(),
        )

        try:
            await self.storage.put(StoredObject(original_key, body, mime_type))
            await self.storage.put(
                StoredObject(thumbnail_key, thumbnail_bytes(body), "image/jpeg")
            )
            persisted = await self.repository.add_image(suite, record)
            if idempotency_key:
                await self.idempotency_store.complete(
                    scope,
                    idempotency_key,
                    fingerprint,
                    response_status=201,
                    response_body=self._image_snapshot(persisted),
                    resource_id=persisted.id,
                )
        except Exception as exc:
            await self.storage.delete(original_key)
            await self.storage.delete(thumbnail_key)
            if idempotency_key:
                await self._record_failure(
                    scope, idempotency_key, fingerprint, exc
                )
            raise
        return persisted

    async def _replay_suite(
        self, claim: IdempotencyClaim, workspace_id: UUID
    ) -> SuiteRecord:
        self._ensure_replayable(claim)
        resource_id = claim.record.resource_id
        suite = (
            await self.repository.get_suite(resource_id, workspace_id)
            if resource_id
            else None
        )
        if suite is None:
            raise AppError(
                "IDEMPOTENCY_RESOURCE_MISSING",
                "the original idempotent resource no longer exists",
                409,
            )
        return suite

    def _replay_image(
        self, claim: IdempotencyClaim, suite: SuiteRecord
    ) -> ImageRecord:
        self._ensure_replayable(claim)
        resource_id = claim.record.resource_id
        image = next(
            (item for item in suite.images if item.id == resource_id), None
        )
        if image is None:
            raise AppError(
                "IDEMPOTENCY_RESOURCE_MISSING",
                "the original idempotent resource no longer exists",
                409,
            )
        return image

    @staticmethod
    def _ensure_replayable(claim: IdempotencyClaim) -> None:
        if claim.record.status == "in_progress":
            raise AppError(
                "IDEMPOTENCY_IN_PROGRESS",
                "an equivalent request is already in progress",
                409,
            )
        if claim.record.status == "failed":
            body = claim.record.response_body or {}
            raise AppError(
                str(body.get("code", "IDEMPOTENCY_PREVIOUSLY_FAILED")),
                str(body.get("message", "the original request failed")),
                claim.record.response_status or 409,
            )

    async def _record_failure(
        self,
        scope: str,
        key: str,
        fingerprint: str,
        exc: Exception,
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

    @staticmethod
    def _suite_snapshot(suite: SuiteRecord) -> dict:
        return {
            "id": str(suite.id),
            "name": suite.name,
            "status": suite.status,
            "createdAt": suite.created_at.isoformat(),
            "updatedAt": suite.updated_at.isoformat(),
        }

    @staticmethod
    def _image_snapshot(image: ImageRecord) -> dict:
        return {
            "id": str(image.id),
            "suiteId": str(image.suite_id),
            "ordinal": image.ordinal,
            "sha256": image.sha256,
            "width": image.width,
            "height": image.height,
            "mimeType": image.mime_type,
            "originalFilename": image.filename,
            "createdAt": image.created_at.isoformat(),
        }

    async def get_input_image_preview(
        self, suite_id: UUID, image_id: UUID, kind: str
    ) -> StoredObject:
        suite = await self.get_suite(suite_id)
        image = (
            next((item for item in suite.images if item.id == image_id), None)
            if suite
            else None
        )
        if image is None:
            raise AppError("INVALID_INPUT_IMAGE", "image does not exist", 404)
        if kind not in {"original", "thumbnail"}:
            raise AppError("NOT_FOUND", "preview does not exist", 404)

        key = image.original_key if kind == "original" else image.thumbnail_key
        stored = await self.storage.get(key)
        if stored is None:
            raise AppError("OBJECT_NOT_FOUND", "preview does not exist", 404)
        return stored
