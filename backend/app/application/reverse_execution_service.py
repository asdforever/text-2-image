"""Application service for the project reverse execution workbench."""

from copy import deepcopy
from typing import Any
from uuid import UUID

from ..core.errors import AppError
from ..reverse_execution_repository import ReverseExecutionPlanRecord
from .reverse_execution import build_execution_plan, compile_task_prompt


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

    async def get(self, project_id: UUID) -> ReverseExecutionPlanRecord | None:
        await self._require_project(project_id)
        return await self.repository.get(self.workspace_id, project_id)

    async def generate(
        self, project_id: UUID, version_id: UUID, *,
        source_asset_id: UUID | None = None,
        product_facts: dict[str, Any] | None = None,
        parameter_brief: str = "",
        output_settings: dict[str, Any] | None = None,
    ) -> ReverseExecutionPlanRecord:
        await self._require_project(project_id)
        version = await self.reverse_project_service.get_version(version_id)
        document = build_execution_plan(version.document, version.id)
        document["sourceAssetId"] = str(source_asset_id) if source_asset_id else None
        document["productFacts"] = deepcopy(product_facts or {})
        document["parameterBrief"] = parameter_brief
        document["outputSettings"] = deepcopy(output_settings or {})
        document["parametersAssigned"] = False
        return await self.repository.create(self.workspace_id, project_id, version.id, document)

    async def save(self, project_id: UUID, expected_revision: int, document: dict[str, Any]) -> ReverseExecutionPlanRecord:
        await self._require_project(project_id)
        current = await self.repository.get(self.workspace_id, project_id)
        if current is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        self._validate_task_identity(current.document, document)
        next_document = deepcopy(document)
        for key in ("parametersAssigned", "parameterSummary", "parameterWarnings", "parameterModelConnection", "outputSettings", "parameterBrief"):
            if key not in next_document and key in current.document:
                next_document[key] = deepcopy(current.document[key])
        inputs_changed = any(next_document.get(key) != current.document.get(key) for key in ("productFacts", "parameterBrief", "sourceAssetId"))
        language_changed = next_document.get("outputSettings", {}).get("outputLanguage") != current.document.get("outputSettings", {}).get("outputLanguage")
        if inputs_changed:
            next_document["parametersAssigned"] = False
            for task in next_document.get("tasks", []):
                task["parametersAssigned"] = False
        previous_tasks = {task["id"]: task for task in current.document.get("tasks", [])}
        for task in next_document.get("tasks", []):
            previous = previous_tasks.get(task["id"], {})
            task_changed = any(task.get(key) != previous.get(key) for key in ("moduleParameters", "structure"))
            if (inputs_changed or language_changed or task_changed) and task.get("promptDraft", "") == previous.get("promptDraft", ""):
                task["promptDraft"] = ""
                task["status"] = "draft"
        next_document["revision"] = expected_revision + 1
        return await self.repository.save(self.workspace_id, project_id, expected_revision, next_document)

    async def compile(
        self,
        project_id: UUID,
        expected_revision: int,
        product_facts: dict[str, Any] | None = None,
    ) -> ReverseExecutionPlanRecord:
        current = await self.get(project_id)
        if current is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        if current.revision != expected_revision:
            raise AppError("REVERSE_EXECUTION_REVISION_CONFLICT", "项目反推方案已被更新，请重新加载", 409)
        if current.document.get("parameterBrief", "").strip() and not current.document.get("parametersAssigned"):
            current = await self.assign_parameters(project_id, current.revision)
        document = deepcopy(current.document)
        facts = product_facts if product_facts is not None else document.get("productFacts", {})
        document["productFacts"] = deepcopy(facts)
        for task in document.get("tasks", []):
            task["promptDraft"] = compile_task_prompt(task, facts, document.get("outputSettings"))
            task["status"] = "compiled"
        return await self.save(project_id, current.revision, document)

    async def assign_parameters(self, project_id: UUID, expected_revision: int) -> ReverseExecutionPlanRecord:
        current = await self.get(project_id)
        if current is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        if current.revision != expected_revision:
            raise AppError("REVERSE_EXECUTION_REVISION_CONFLICT", "项目反推方案已被更新，请重新加载", 409)
        if self.parameter_planner is None:
            raise AppError("REVERSE_PARAMETERS_UNAVAILABLE", "自动填写服务不可用", 503)
        result = await self.parameter_planner.assign(project_id, current.document)
        document = deepcopy(current.document)
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
        return await self.save(project_id, current.revision, document)

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
