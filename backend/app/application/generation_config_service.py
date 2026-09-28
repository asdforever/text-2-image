from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from ..core.errors import AppError
from ..core.identity import IdentityProvider
from ..generation_config_catalog import (
    create_default_generation_config,
    normalize_generation_config,
)
from ..generation_config_repository import ConfigDraftRecord, ConfigVersionRecord
from .idempotency import IdempotencyClaim, request_fingerprint
from .ports import Clock, IdempotencyStore
from .runtime_module_catalog import runtime_catalog_snapshot


class GenerationConfigService:
    """管理当前工作区生成配置的草稿与不可变发布版本。"""

    def __init__(
        self,
        repository: Any,
        identity_provider: IdentityProvider,
        idempotency_store: IdempotencyStore,
        clock: Clock,
        prompt_repository: Any | None = None,
    ) -> None:
        self.repository = repository
        self.identity_provider = identity_provider
        self.idempotency_store = idempotency_store
        self.clock = clock
        self.prompt_repository = prompt_repository
        self.model_connections = None

    async def get_published(self) -> ConfigVersionRecord:
        workspace_id = self._workspace_id()
        content = create_default_generation_config()
        content["savedAt"] = self._timestamp()
        current, _ = await self.repository.bootstrap(workspace_id, content)
        return current

    async def get_version(self, version_no: int) -> ConfigVersionRecord | None:
        return await self.repository.get_version(self._workspace_id(), version_no)

    async def resolve_published(self) -> dict[str, Any]:
        published = await self.get_published()
        config = deepcopy(published.content)
        prompt_bindings = []
        for field in (
            "marketBindings",
            "modelBindings",
            "heroBindings",
            "suiteBindings",
        ):
            prompt_bindings.extend(
                deepcopy(binding)
                for binding in config.get(field, {}).values()
                if binding is not None
            )
        return {
            "configVersion": published.version_no,
            "contentSha256": published.content_sha256,
            "config": config,
            "runtimeModules": runtime_catalog_snapshot(config),
            "promptBindings": prompt_bindings,
        }

    async def get_draft(self) -> ConfigDraftRecord:
        workspace_id = self._workspace_id()
        content = create_default_generation_config()
        content["savedAt"] = self._timestamp()
        _, draft = await self.repository.bootstrap(workspace_id, content)
        return draft

    async def replace_draft(
        self,
        content: dict[str, Any],
        base_version_no: int,
        idempotency_key: str | None = None,
    ) -> ConfigDraftRecord:
        normalized = normalize_generation_config(content)
        workspace_id = self._workspace_id()
        if not idempotency_key:
            return await self.repository.replace_draft_if_current(
                workspace_id, base_version_no, normalized
            )
        fingerprint = request_fingerprint(
            {"baseVersion": base_version_no, "content": normalized}
        )
        scope = f"{workspace_id}:PUT:/api/generation-config/draft"
        claim = await self.idempotency_store.claim(scope, idempotency_key, fingerprint)
        if not claim.is_owner:
            if claim.record.status == "in_progress":
                return await self._recover_draft_write(
                    claim, workspace_id, base_version_no, normalized, scope, idempotency_key,
                    fingerprint,
                )
            return self._draft_from_claim(claim)
        try:
            draft = await self.repository.replace_draft_if_current(
                workspace_id, base_version_no, normalized
            )
            await self.idempotency_store.complete(
                scope,
                idempotency_key,
                fingerprint,
                response_status=200,
                response_body=self._draft_snapshot(draft),
                resource_id=workspace_id,
            )
            return draft
        except Exception as exc:
            await self._record_failure(scope, idempotency_key, fingerprint, exc)
            raise

    async def discard_draft(
        self, idempotency_key: str | None = None
    ) -> ConfigDraftRecord:
        workspace_id = self._workspace_id()
        scope = f"{workspace_id}:DELETE:/api/generation-config/draft"
        fingerprint = request_fingerprint({"action": "discard"})
        claim = None
        if idempotency_key:
            claim = await self.idempotency_store.claim(scope, idempotency_key, fingerprint)
            if not claim.is_owner:
                return self._draft_from_claim(claim)
        try:
            await self.get_published()
            draft = await self.repository.reset_draft(workspace_id)
            if idempotency_key:
                await self.idempotency_store.complete(
                    scope,
                    idempotency_key,
                    fingerprint,
                    response_status=200,
                    response_body=self._draft_snapshot(draft),
                    resource_id=workspace_id,
                )
            return draft
        except Exception as exc:
            if idempotency_key:
                await self._record_failure(scope, idempotency_key, fingerprint, exc)
            raise

    async def publish(self, idempotency_key: str | None = None) -> ConfigVersionRecord:
        workspace_id = self._workspace_id()
        scope = f"{workspace_id}:POST:/api/generation-config/publish"
        content = create_default_generation_config()
        content["savedAt"] = self._timestamp()
        current, draft = await self.repository.bootstrap(workspace_id, content)
        content = normalize_generation_config(draft.content)
        fingerprint = request_fingerprint({"content": self._request_content(content)})
        if idempotency_key:
            claim = await self.idempotency_store.claim(scope, idempotency_key, fingerprint)
            if not claim.is_owner:
                if claim.record.status == "in_progress":
                    return await self._recover_publish(
                        claim, workspace_id, content, scope, idempotency_key, fingerprint
                    )
                return await self._published_from_claim(claim, workspace_id)
        try:
            if content.get("promptModel") and self.model_connections is None:
                raise AppError("MODEL_CONNECTION_SERVICE_UNAVAILABLE", "模型连接服务当前不可用，无法发布提示词模型", 503)
            if self.model_connections is not None:
                for model in content.get("models", []):
                    if model.get("connectionId"):
                        await self.model_connections.snapshot(model)
                if content.get("promptModel"):
                    await self.model_connections.prompt_snapshot(content["promptModel"])
            content = await self._resolve_prompt_bindings(content)
            published = await self.repository.publish_draft(
                workspace_id,
                draft.base_version_no,
                draft.content,
                content,
                self._timestamp(),
            )
            if idempotency_key:
                await self.idempotency_store.complete(
                    scope,
                    idempotency_key,
                    fingerprint,
                    response_status=200,
                    response_body=self._version_snapshot(published),
                    resource_id=published.id,
                )
            return published
        except Exception as exc:
            if idempotency_key:
                await self._record_failure(scope, idempotency_key, fingerprint, exc)
            raise

    def _workspace_id(self) -> UUID:
        return self.identity_provider.get_context().workspace_id

    async def _resolve_prompt_bindings(
        self, content: dict[str, Any]
    ) -> dict[str, Any]:
        resolved = deepcopy(content)
        slots = {
            "marketBindings": "market",
            "modelBindings": "model",
            "heroBindings": "hero-module",
            "suiteBindings": "suite-module",
        }
        for field, slot in slots.items():
            for target_id, binding in resolved[field].items():
                if binding is None:
                    continue
                if not isinstance(binding, dict):
                    raise AppError(
                        "GENERATION_CONFIG_PROMPT_BINDING_INVALID",
                        f"条目“{target_id}”的提示词绑定格式无效",
                        400,
                    )
                try:
                    template_id = UUID(str(binding["promptTemplateId"]))
                    version_id = UUID(str(binding["promptVersionId"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise AppError(
                        "GENERATION_CONFIG_PROMPT_BINDING_INVALID",
                        f"条目“{target_id}”的提示词绑定不完整",
                        400,
                    ) from exc
                if self.prompt_repository is None:
                    raise AppError(
                        "GENERATION_CONFIG_PROMPT_SERVICE_UNAVAILABLE",
                        "提示词服务当前不可用，无法发布绑定",
                        503,
                    )
                version = await self.prompt_repository.get_version(version_id)
                if version is None:
                    raise AppError(
                        "GENERATION_CONFIG_PROMPT_VERSION_NOT_FOUND",
                        f"条目“{target_id}”引用的提示词版本不存在",
                        400,
                    )
                if version.template_id != template_id:
                    raise AppError(
                        "GENERATION_CONFIG_PROMPT_OWNERSHIP",
                        f"条目“{target_id}”的提示词版本不属于指定模板",
                        400,
                    )
                template = await self.prompt_repository.get_template(template_id)
                if template is None:
                    raise AppError(
                        "GENERATION_CONFIG_PROMPT_TEMPLATE_NOT_FOUND",
                        f"条目“{target_id}”引用的提示词模板不存在",
                        400,
                    )
                resolved[field][target_id] = {
                    "promptTemplateId": str(template.id),
                    "promptVersionId": str(version.id),
                    "templateName": template.name,
                    "versionNo": version.version_no,
                    "contentSha256": version.content_sha256,
                    "slot": slot,
                    "targetId": target_id,
                }
        return resolved

    def _timestamp(self) -> str:
        return self.clock.now().isoformat().replace("+00:00", "Z")

    @staticmethod
    def _comparable(content: dict[str, Any]) -> dict[str, Any]:
        comparable = deepcopy(content)
        comparable.pop("version", None)
        comparable.pop("savedAt", None)
        return comparable

    @classmethod
    def _request_content(cls, content: dict[str, Any]) -> dict[str, Any]:
        comparable = cls._comparable(content)
        comparable.pop("plannerBindings", None)
        for field in (
            "marketBindings",
            "modelBindings",
            "heroBindings",
            "suiteBindings",
        ):
            comparable[field] = {
                target_id: (
                    {
                        "promptTemplateId": binding.get("promptTemplateId"),
                        "promptVersionId": binding.get("promptVersionId"),
                    }
                    if isinstance(binding, dict)
                    else binding
                )
                for target_id, binding in comparable[field].items()
            }
        return comparable

    @staticmethod
    def _draft_snapshot(draft: ConfigDraftRecord) -> dict[str, Any]:
        return {
            "workspaceId": str(draft.workspace_id),
            "baseVersion": draft.base_version_no,
            "content": deepcopy(draft.content),
            "updatedAt": draft.updated_at.isoformat(),
        }

    @staticmethod
    def _version_snapshot(version: ConfigVersionRecord) -> dict[str, Any]:
        return {
            "id": str(version.id),
            "workspaceId": str(version.workspace_id),
            "version": version.version_no,
            "content": deepcopy(version.content),
            "contentSha256": version.content_sha256,
            "createdAt": version.created_at.isoformat(),
        }

    @staticmethod
    def _ensure_replayable(claim: IdempotencyClaim) -> dict[str, Any]:
        if claim.record.status == "in_progress":
            raise AppError(
                "IDEMPOTENCY_IN_PROGRESS",
                "相同请求正在处理中",
                409,
            )
        body = claim.record.response_body or {}
        if claim.record.status == "failed":
            raise AppError(
                str(body.get("code", "IDEMPOTENCY_PREVIOUSLY_FAILED")),
                str(body.get("message", "首次请求已失败")),
                claim.record.response_status or 409,
            )
        return body

    def _draft_from_claim(self, claim: IdempotencyClaim) -> ConfigDraftRecord:
        body = self._ensure_replayable(claim)
        return ConfigDraftRecord(
            UUID(body["workspaceId"]),
            int(body["baseVersion"]),
            deepcopy(body["content"]),
            datetime.fromisoformat(body["updatedAt"]),
        )

    async def _recover_draft_write(
        self,
        claim: IdempotencyClaim,
        workspace_id: UUID,
        base_version_no: int,
        content: dict[str, Any],
        scope: str,
        key: str,
        fingerprint: str,
    ) -> ConfigDraftRecord:
        draft = await self.repository.get_draft(workspace_id)
        if (
            draft is None
            or draft.base_version_no != base_version_no
            or self._comparable(draft.content) != self._comparable(content)
        ):
            return self._draft_from_claim(claim)
        await self.idempotency_store.complete(
            scope,
            key,
            fingerprint,
            response_status=200,
            response_body=self._draft_snapshot(draft),
            resource_id=workspace_id,
        )
        return draft

    async def _published_from_claim(
        self, claim: IdempotencyClaim, workspace_id: UUID
    ) -> ConfigVersionRecord:
        body = self._ensure_replayable(claim)
        version = await self.repository.get_version(workspace_id, int(body["version"]))
        if version is None:
            raise AppError(
                "IDEMPOTENCY_RESOURCE_MISSING",
                "首次发布的配置版本已不存在",
                409,
            )
        return version

    async def _recover_publish(
        self,
        claim: IdempotencyClaim,
        workspace_id: UUID,
        content: dict[str, Any],
        scope: str,
        key: str,
        fingerprint: str,
    ) -> ConfigVersionRecord:
        for version in reversed(await self.repository.list_versions(workspace_id)):
            if self._request_content(version.content) != self._request_content(content):
                continue
            await self.idempotency_store.complete(
                scope,
                key,
                fingerprint,
                response_status=200,
                response_body=self._version_snapshot(version),
                resource_id=version.id,
            )
            return version
        return await self._published_from_claim(claim, workspace_id)

    async def _record_failure(
        self, scope: str, key: str, fingerprint: str, exc: Exception
    ) -> None:
        code = exc.code if isinstance(exc, AppError) else "DEPENDENCY_FAILURE"
        message = exc.message if isinstance(exc, AppError) else "请求依赖失败"
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
