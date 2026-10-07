from typing import Any
from uuid import UUID

from ..core.errors import AppError
from ..core.identity import IdentityProvider
from ..project_repository import ProjectRecord, ProjectSummaryRecord
from .idempotency import IdempotencyClaim, request_fingerprint
from .ports import IdempotencyStore


class ProjectService:
    """协调项目生命周期与服务端身份范围。"""

    def __init__(
        self,
        repository: Any,
        identity_provider: IdentityProvider,
        idempotency_store: IdempotencyStore,
        *,
        project_archive: Any | None = None,
    ) -> None:
        self.repository = repository
        self.identity_provider = identity_provider
        self.idempotency_store = idempotency_store
        self.project_archive = project_archive

    async def create_project(
        self, name: str, idempotency_key: str | None = None
    ) -> ProjectRecord:
        normalized_name = self._normalized_name(name)
        context = self.identity_provider.get_context()
        if not idempotency_key:
            project = await self.repository.create_project(normalized_name, context.workspace_id)
            await self._ensure_project_archive(project)
            return project

        scope = f"{context.workspace_id}:POST:/api/projects"
        fingerprint = request_fingerprint({"name": normalized_name})
        claim = await self.idempotency_store.claim(scope, idempotency_key, fingerprint)
        if not claim.is_owner:
            project = await self._replay_project(claim, context.workspace_id)
            await self._ensure_project_archive(project)
            return project
        try:
            project = await self.repository.create_project(normalized_name, context.workspace_id)
            await self._ensure_project_archive(project)
            await self.idempotency_store.complete(
                scope,
                idempotency_key,
                fingerprint,
                response_status=201,
                response_body=self._snapshot(project),
                resource_id=project.id,
            )
            return project
        except Exception as exc:
            await self._record_failure(scope, idempotency_key, fingerprint, exc)
            raise

    async def _ensure_project_archive(self, project: ProjectRecord) -> None:
        if self.project_archive is not None:
            await self.project_archive.ensure_project_archive(project)

    async def _archive_project_archive(self, project_id: UUID) -> None:
        if self.project_archive is not None:
            await self.project_archive.archive_project_archive(project_id)

    async def _delete_project_archive(self, project_id: UUID) -> None:
        if self.project_archive is not None:
            await self.project_archive.delete_project_archive(project_id)

    async def list_projects(self, *, include_archived: bool = False) -> list[ProjectRecord]:
        context = self.identity_provider.get_context()
        return await self.repository.list_projects(
            context.workspace_id, include_archived=include_archived
        )

    async def get_project(self, project_id: UUID) -> ProjectRecord | None:
        context = self.identity_provider.get_context()
        return await self.repository.get_project(project_id, context.workspace_id)

    async def list_project_summaries(self, *, include_archived: bool = False) -> list[ProjectSummaryRecord]:
        context = self.identity_provider.get_context()
        return await self.repository.list_project_summaries(
            context.workspace_id, include_archived=include_archived
        )

    async def archive_project(
        self, project_id: UUID, idempotency_key: str | None = None
    ) -> ProjectRecord | None:
        context = self.identity_provider.get_context()
        if not idempotency_key:
            project = await self.repository.archive_project(project_id, context.workspace_id)
            if project is not None:
                await self._archive_project_archive(project.id)
            return project
        scope = f"{context.workspace_id}:POST:/api/projects/{project_id}/archive"
        fingerprint = request_fingerprint({"projectId": str(project_id), "action": "archive"})
        claim = await self.idempotency_store.claim(scope, idempotency_key, fingerprint)
        if not claim.is_owner:
            project = await self._replay_project(claim, context.workspace_id)
            await self._archive_project_archive(project.id)
            return project
        try:
            project = await self.repository.archive_project(project_id, context.workspace_id)
            if project is None:
                raise AppError("INVALID_PROJECT_ID", "project does not exist", 404)
            await self._archive_project_archive(project.id)
            await self.idempotency_store.complete(
                scope,
                idempotency_key,
                fingerprint,
                response_status=200,
                response_body=self._snapshot(project),
                resource_id=project.id,
            )
            return project
        except Exception as exc:
            await self._record_failure(scope, idempotency_key, fingerprint, exc)
            raise

    async def delete_project(
        self, project_id: UUID, idempotency_key: str | None = None
    ) -> bool:
        context = self.identity_provider.get_context()
        if not idempotency_key:
            await self._delete_project_archive(project_id)
            deleted = await self.repository.delete_project(project_id, context.workspace_id)
            return deleted
        scope = f"{context.workspace_id}:DELETE:/api/projects/{project_id}"
        fingerprint = request_fingerprint({"projectId": str(project_id), "action": "delete"})
        claim = await self.idempotency_store.claim(scope, idempotency_key, fingerprint)
        if not claim.is_owner:
            self._ensure_replayable(claim)
            return bool((claim.record.response_body or {}).get("deleted"))
        try:
            await self._delete_project_archive(project_id)
            deleted = await self.repository.delete_project(project_id, context.workspace_id)
            await self.idempotency_store.complete(
                scope,
                idempotency_key,
                fingerprint,
                response_status=204,
                response_body={"deleted": deleted},
                resource_id=project_id if deleted else None,
            )
            return deleted
        except Exception as exc:
            await self._record_failure(scope, idempotency_key, fingerprint, exc)
            raise

    @staticmethod
    def _normalized_name(name: str) -> str:
        normalized = name.strip() if isinstance(name, str) else ""
        if not normalized:
            raise AppError("INVALID_PROJECT_NAME", "project name must not be blank", 400)
        return normalized

    async def _replay_project(
        self, claim: IdempotencyClaim, workspace_id: UUID
    ) -> ProjectRecord:
        self._ensure_replayable(claim)
        project = (
            await self.repository.get_project(claim.record.resource_id, workspace_id)
            if claim.record.resource_id
            else None
        )
        if project is None:
            raise AppError(
                "IDEMPOTENCY_RESOURCE_MISSING",
                "the original idempotent resource no longer exists",
                409,
            )
        return project

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

    @staticmethod
    def _snapshot(project: ProjectRecord) -> dict[str, str]:
        return {
            "id": str(project.id),
            "name": project.name,
            "status": project.status,
            "createdAt": project.created_at.isoformat(),
            "updatedAt": project.updated_at.isoformat(),
        }
