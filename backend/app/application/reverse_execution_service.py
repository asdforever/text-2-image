"""Application service for the project reverse execution workbench."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from ..core.errors import AppError
from ..reverse_execution_repository import ReverseExecutionPlanRecord
from .reverse_execution import build_execution_plan, compile_task_prompt
from .reverse_product_images import normalize_auxiliary_ids


class ReverseExecutionService:
    def __init__(self, repository, identity_provider, project_repository, reverse_project_service, *, parameter_planner=None) -> None:
        self.repository = repository
        self.identity_provider = identity_provider
        self.project_repository = project_repository
        self.reverse_project_service = reverse_project_service
        self.parameter_planner = parameter_planner

    @property
    def workspace_id(self) -> UUID:
        return self.identity_provider.get_context().workspace_id

    async def list(self, project_id: UUID) -> list[ReverseExecutionPlanRecord]:
        await self._require_project(project_id)
        return [self._without_prompt_cache(record) for record in await self.repository.list(self.workspace_id, project_id)]

    async def get(self, project_id: UUID, plan_id: UUID | None = None) -> ReverseExecutionPlanRecord | None:
        await self._require_project(project_id)
        record = await self.repository.get(self.workspace_id, project_id, plan_id)
        return self._without_prompt_cache(record) if record else None

    async def generate(
        self, project_id: UUID, version_id: UUID, *,
        source_asset_id: UUID | None = None,
        auxiliary_source_asset_ids: list[UUID] | None = None,
        product_facts: dict[str, Any] | None = None,
        parameter_brief: str = "",
        output_settings: dict[str, Any] | None = None,
        name: str = "",
    ) -> ReverseExecutionPlanRecord:
        await self._require_project(project_id)
        version = await self.reverse_project_service.get_version(version_id)
        document = build_execution_plan(version.document, version.id)
        document["name"] = self._name(name or f"{version.document.get('name') or '反推'} · 方案")
        document["sourceAssetId"] = str(source_asset_id) if source_asset_id else None
        document["auxiliarySourceAssetIds"] = await self.validate_auxiliary_assets(project_id, auxiliary_source_asset_ids, source_asset_id)
        document["productFacts"] = deepcopy(product_facts or {})
        document["parameterBrief"] = parameter_brief
        document["outputSettings"] = deepcopy(output_settings or {})
        document["parametersAssigned"] = False
        return await self.repository.create(self.workspace_id, project_id, version.id, document)

    async def save(self, project_id: UUID, expected_revision: int, document: dict[str, Any], *, plan_id: UUID | None = None) -> ReverseExecutionPlanRecord:
        await self._require_project(project_id)
        current = await self.repository.get(self.workspace_id, project_id, plan_id)
        if current is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        self._validate_task_identity(current.document, document)
        next_document = deepcopy(document)
        if next_document.get("versionId") != current.document.get("versionId"):
            raise AppError("REVERSE_EXECUTION_TASKS_INVALID", "方案的参考版本不可修改，请新增方案", 400)
        next_document["name"] = self._name(next_document.get("name") or current.document.get("name") or "反推方案")
        for key in ("parametersAssigned", "parameterSummary", "parameterWarnings", "parameterModelConnection", "outputSettings", "parameterBrief", "auxiliarySourceAssetIds"):
            if key not in next_document and key in current.document:
                next_document[key] = deepcopy(current.document[key])
        next_document["auxiliarySourceAssetIds"] = await self.validate_auxiliary_assets(project_id, next_document.get("auxiliarySourceAssetIds"), next_document.get("sourceAssetId"))
        inputs_changed = any(next_document.get(key) != current.document.get(key) for key in ("productFacts", "parameterBrief", "sourceAssetId", "auxiliarySourceAssetIds"))
        language_changed = next_document.get("outputSettings", {}).get("outputLanguage") != current.document.get("outputSettings", {}).get("outputLanguage")
        if inputs_changed:
            next_document["parametersAssigned"] = False
            for task in next_document.get("tasks", []):
                task["parametersAssigned"] = False
        previous_tasks = {task["id"]: task for task in current.document.get("tasks", [])}
        for task in next_document.get("tasks", []):
            previous = previous_tasks.get(task["id"], {})
            task_changed = any(task.get(key) != previous.get(key) for key in ("moduleParameters", "structure"))
            task["promptDraft"] = ""
            if inputs_changed or language_changed or task_changed or task.get("status") == "compiled":
                task["status"] = "draft"
        next_document["revision"] = expected_revision + 1
        return await self.repository.save(self.workspace_id, project_id, expected_revision, next_document, plan_id=current.id)

    async def compile(
        self,
        project_id: UUID,
        expected_revision: int,
        product_facts: dict[str, Any] | None = None,
        *, plan_id: UUID | None = None,
    ) -> ReverseExecutionPlanRecord:
        current = await self.get(project_id, plan_id)
        if current is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        if current.revision != expected_revision:
            raise AppError("REVERSE_EXECUTION_REVISION_CONFLICT", "项目反推方案已被更新，请重新加载", 409)
        document = deepcopy(current.document)
        facts = product_facts if product_facts is not None else document.get("productFacts", {})
        if facts != document.get("productFacts", {}):
            document["parametersAssigned"] = False
            for task in document.get("tasks", []):
                task["parametersAssigned"] = False
        document["productFacts"] = deepcopy(facts)
        if document.get("parameterBrief", "").strip() and not document.get("parametersAssigned"):
            document = await self._assign_document(project_id, document)
        # Commit only after assignment succeeds so a failed preview stays retryable.
        document["revision"] = current.revision + 1
        current = await self.repository.save(self.workspace_id, project_id, current.revision, document, plan_id=current.id)
        # Compilation is a preview. Persist inputs, never the derived prompt.
        preview = deepcopy(current)
        for task in preview.document.get("tasks", []):
            task["promptDraft"] = compile_task_prompt(task, facts, preview.document.get("outputSettings"), product_image_count=1 + len(preview.document.get("auxiliarySourceAssetIds", [])))
            task["status"] = "compiled"
        return preview

    @staticmethod
    def _without_prompt_cache(record: ReverseExecutionPlanRecord) -> ReverseExecutionPlanRecord:
        result = deepcopy(record)
        for task in result.document.get("tasks", []):
            task["promptDraft"] = ""
            if task.get("status") == "compiled":
                task["status"] = "draft"
        return result

    async def assign_parameters(self, project_id: UUID, expected_revision: int, *, plan_id: UUID | None = None) -> ReverseExecutionPlanRecord:
        current = await self.get(project_id, plan_id)
        if current is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        if current.revision != expected_revision:
            raise AppError("REVERSE_EXECUTION_REVISION_CONFLICT", "项目反推方案已被更新，请重新加载", 409)
        document = await self._assign_document(project_id, current.document)
        return await self.save(project_id, current.revision, document, plan_id=current.id)

    async def validate_auxiliary_assets(self, project_id, value, primary_id=None):
        ids = normalize_auxiliary_ids(value, primary_id)
        for asset_id in ids:
            asset = await self.project_repository.get_asset(UUID(asset_id), self.workspace_id)
            if asset is None or asset.project_id != project_id or asset.state != "available" or asset.kind not in {"source", "white_background"}:
                raise AppError("REVERSE_PRODUCT_IMAGES_INVALID", "辅助商品图必须属于当前项目且是可用的商品素材", 400)
        return ids

    async def _assign_document(self, project_id: UUID, source: dict[str, Any]) -> dict[str, Any]:
        if self.parameter_planner is None:
            raise AppError("REVERSE_PARAMETERS_UNAVAILABLE", "自动填写服务不可用", 503)
        result = await self.parameter_planner.assign(project_id, source)
        document = deepcopy(source)
        parameters = {task["taskId"]: task["moduleParameters"] for task in result["tasks"]}
        for task in document.get("tasks", []):
            task["moduleParameters"] = parameters[task["id"]]
            task["parametersAssigned"] = True
            task["promptDraft"] = ""
            task["status"] = "draft"
        document["parametersAssigned"] = True
        document["parameterSummary"] = result["summary"]
        document["parameterWarnings"] = result["warnings"]
        document["parameterModelConnection"] = result["promptModelConnection"]
        return document

    @staticmethod
    def _name(value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 100:
            raise AppError("REVERSE_EXECUTION_NAME_INVALID", "方案名称需要1到100个字符", 400)
        return value.strip()

    async def _require_project(self, project_id: UUID) -> None:
        project = await self.project_repository.get_project(project_id, self.workspace_id)
        if project is None:
            raise AppError("INVALID_PROJECT_ID", "项目不存在", 404)

    @staticmethod
    def _validate_task_identity(current: dict[str, Any], incoming: dict[str, Any]) -> None:
        current_identity = [
            (item.get("ordinal"), item.get("referenceImageId"))
            for item in current.get("tasks", [])
        ]
        incoming_identity = [
            (item.get("ordinal"), item.get("referenceImageId"))
            for item in incoming.get("tasks", [])
        ]
        if current_identity != incoming_identity:
            raise AppError("REVERSE_EXECUTION_TASKS_INVALID", "项目反推任务必须保持模板顺序和一一对应关系", 400)
