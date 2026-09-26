from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from ..core.errors import AppError
from ..core.identity import IdentityProvider
from ..workbench_repository import (
    InMemoryWorkbenchRepository,
    WorkbenchTaskInput,
    WorkbenchTaskRecord,
    WorkbenchTaskVersionRecord,
    WorkbenchVersionInput,
    WorkbenchLayoutRecord,
    WorkbenchReferenceRecord,
)


class WorkbenchService:
    def __init__(self, repository: InMemoryWorkbenchRepository, identity_provider: IdentityProvider, suite_planning_service: Any = None, batch_repository: Any = None, suite_service: Any = None, project_repository: Any = None) -> None:
        self.repository = repository
        self.identity_provider = identity_provider
        self.suite_planning_service = suite_planning_service
        self.batch_repository = batch_repository
        self.suite_service = suite_service
        self.project_repository = project_repository

    def _scope(self) -> UUID:
        return self.identity_provider.get_context().workspace_id

    @staticmethod
    def _plan_snapshot_view(detail: Any) -> dict[str, Any] | None:
        if detail is None:
            return None
        plan = getattr(detail, "plan", detail)
        snapshot = dict(getattr(plan, "snapshot", {}) or {})
        modules = list(getattr(detail, "modules", []) or [])
        items = [
            {
                "id": str(module.id),
                "ordinal": int(module.position),
                "imageType": str((getattr(module, "prompt_snapshot", {}) or {}).get("imageType", "detail")),
                "title": module.title,
                "purpose": module.copy_summary,
                "prompt": module.current_task_prompt or module.compiled_task_prompt or "",
            }
            for module in sorted(modules, key=lambda item: item.position)
        ]
        return {
            "id": str(plan.id),
            "revisionNumber": int(getattr(plan, "revision", 1)),
            "revisionKind": "human" if getattr(plan, "confirmed_snapshot", None) else "llm",
            "templateVersionId": str(snapshot.get("templateVersionId", "")),
            "dynamicInput": snapshot.get("dynamicInput", {}),
            "humanInput": snapshot.get("humanInput", {}),
            "chunks": snapshot.get("chunks", []),
            "inputImageIds": snapshot.get("sourceAssetIds", snapshot.get("sourceAssets", [])),
            "provider": snapshot.get("provider", {"name": "internal", "model": "", "isFake": True}),
            "items": items,
            "phase": "legacy_plan",
            "confirmationStatus": "confirmed" if getattr(plan, "status", "") == "confirmed" else "draft",
            "confirmedAt": getattr(plan, "confirmed_at", None).isoformat() if getattr(plan, "confirmed_at", None) else None,
            "createdAt": getattr(plan, "created_at", datetime.now(timezone.utc)).isoformat(),
        }

    async def create_tasks(self, project_id: UUID, plan_snapshot_id: UUID, idempotency_key: str, inputs: list[WorkbenchTaskInput]):
        return await self.repository.create_tasks(self._scope(), project_id, plan_snapshot_id, idempotency_key, inputs)

    async def create_tasks_from_plan(self, project_id: UUID, plan_snapshot_id: UUID, idempotency_key: str):
        if self.suite_planning_service is None:
            raise AppError("WORKBENCH_PLAN_UNAVAILABLE", "详情页规划服务不可用", 503)
        detail = await self.suite_planning_service.get_plan(project_id, plan_snapshot_id)
        if detail.plan.status != "confirmed":
            raise AppError("WORKBENCH_PLAN_NOT_CONFIRMED", "详情页规划尚未确认，不能进入工作台", 409)
        inputs = [
            WorkbenchTaskInput(
                module.id,
                module.position,
                module.title,
                module.copy_summary,
                module.current_task_prompt or module.compiled_task_prompt or "",
                {"resultCount": module.requested_image_count, **(module.module_parameters[0] if module.module_parameters and isinstance(module.module_parameters[0], dict) else {})},
                str((getattr(module, "prompt_snapshot", {}) or {}).get("imageType", "detail")),
            )
            for module in detail.modules
        ]
        return await self.create_tasks(project_id, plan_snapshot_id, idempotency_key, inputs)

    async def get_workbench(self, project_id: UUID) -> dict[str, Any]:
        tasks = await self.list_tasks(project_id)
        versions = {task.id: await self.list_versions(task.id) for task in tasks}
        batches: list[Any] = []
        plan = None
        detail = None
        if self.suite_planning_service is not None:
            try:
                detail = await self.suite_planning_service.get_latest_plan(project_id)
                plan = self._plan_snapshot_view(detail)
            except Exception:
                plan = None
        if self.batch_repository is not None:
            batch_id = getattr(getattr(detail, "plan", None), "generation_batch_id", None)
            if batch_id is not None:
                batch = await self.batch_repository.get_batch(batch_id, self._scope())
                if batch is not None:
                    batches.append({"id": str(batch.id), "suiteId": str(project_id), "kind": "batch", "requestedCount": 0, "taskIds": [str(task.id) for task in tasks], "status": str(batch.status), "idempotencyKey": getattr(batch, "confirm_idempotency_key", None) or getattr(batch, "compile_idempotency_key", ""), "createdAt": batch.created_at.isoformat(), "startedAt": None, "finishedAt": batch.completed_at.isoformat() if getattr(batch, "completed_at", None) else None})
        input_images: list[dict[str, Any]] = []
        if self.project_repository is not None:
            for ordinal, asset in enumerate(await self.project_repository.list_assets(project_id, self._scope()), start=1):
                if getattr(asset, "kind", "") != "source":
                    continue
                input_images.append({"id": str(asset.id), "suiteId": str(project_id), "ordinal": ordinal, "originalObjectKey": "", "thumbnailObjectKey": "", "sha256": "", "width": 1, "height": 1, "mimeType": "image/png", "originalFilename": "", "currentBaseVersionId": None, "createdAt": asset.created_at.isoformat(), "originalPreviewUrl": f"/api/projects/{project_id}/assets/{asset.id}/preview", "thumbnailPreviewUrl": f"/api/projects/{project_id}/assets/{asset.id}/preview"})
        suite = {"id": str(project_id), "name": "", "status": "active", "createdAt": "", "updatedAt": ""}
        if self.project_repository is not None:
            project = await self.project_repository.get_project(project_id, self._scope())
            if project is not None:
                suite.update({"name": project.name, "status": project.status, "createdAt": project.created_at.isoformat(), "updatedAt": project.updated_at.isoformat()})
        return {"suite": suite, "inputImages": input_images, "planSnapshot": plan, "tasks": [(task, versions[task.id]) for task in tasks], "batches": batches, "layout": await self.get_layout(project_id), "references": await self.list_references(project_id)}

    async def list_tasks(self, project_id: UUID, include_archived: bool = False) -> list[WorkbenchTaskRecord]:
        return await self.repository.list_tasks(project_id, self._scope(), include_archived)

    async def get_task(self, task_id: UUID) -> WorkbenchTaskRecord | None:
        return await self.repository.get_task(task_id, self._scope())

    async def update_task(self, task_id: UUID, expected_revision: int, changes: dict[str, Any]) -> WorkbenchTaskRecord:
        return await self.repository.update_task(task_id, self._scope(), expected_revision, changes)

    async def archive_task(self, task_id: UUID) -> WorkbenchTaskRecord:
        return await self.repository.archive_task(task_id, self._scope())

    async def start_task_generation(self, task_id: UUID, expected_revision: int) -> Any:
        """Validate a task snapshot and hand generation back to the existing batch boundary.

        The workbench deliberately does not call an image provider.  Confirmed plan
        batches are the execution boundary owned by the batch-generation service;
        this method only resolves and returns that batch for polling.
        """
        task = await self.get_task(task_id)
        if task is None:
            raise AppError("WORKBENCH_TASK_NOT_FOUND", "工作台任务不存在", 404)
        if task.archived_at is not None:
            raise AppError("WORKBENCH_TASK_ARCHIVED", "已归档任务不可生成", 409)
        if task.prompt_revision != expected_revision:
            raise AppError("WORKBENCH_TASK_REVISION_CONFLICT", "任务已被其他编辑更新，请刷新后重试", 409)
        if self.suite_planning_service is None or self.batch_repository is None:
            raise AppError("WORKBENCH_GENERATION_UNAVAILABLE", "生成批次服务不可用", 503)
        if task.plan_snapshot_id is None:
            raise AppError("WORKBENCH_PLAN_REQUIRED", "任务缺少已确认规划，不能生成", 409)
        detail = await self.suite_planning_service.get_plan(task.project_id, task.plan_snapshot_id)
        plan = getattr(detail, "plan", None)
        if plan is None or getattr(plan, "status", None) != "confirmed":
            raise AppError("WORKBENCH_PLAN_NOT_CONFIRMED", "详情页规划尚未确认，不能生成", 409)
        batch_id = getattr(plan, "generation_batch_id", None)
        if batch_id is None:
            raise AppError("WORKBENCH_BATCH_NOT_FOUND", "规划尚未创建生成批次", 409)
        batch = await self.batch_repository.get_batch(batch_id, self._scope())
        if batch is None:
            raise AppError("WORKBENCH_BATCH_NOT_FOUND", "生成批次不存在", 404)
        return batch

    async def start_batch_generation(self, project_id: UUID, task_ids: list[UUID] | None = None) -> Any:
        """Resolve the confirmed plan batch for a set of active workbench tasks."""
        tasks = await self.list_tasks(project_id)
        selected = [task for task in tasks if task_ids is None or task.id in set(task_ids)]
        if not selected:
            raise AppError("WORKBENCH_TASKS_INVALID", "没有可生成的工作台任务", 400)
        if any(task.archived_at is not None for task in selected):
            raise AppError("WORKBENCH_TASK_ARCHIVED", "已归档任务不可生成", 409)
        plan_ids = {task.plan_snapshot_id for task in selected}
        if len(plan_ids) != 1 or None in plan_ids:
            raise AppError("WORKBENCH_PLAN_REQUIRED", "任务缺少统一的已确认规划，不能批量生成", 409)
        return await self.start_task_generation(selected[0].id, selected[0].prompt_revision)

    async def add_version(self, task_id: UUID, input: WorkbenchVersionInput) -> WorkbenchTaskVersionRecord:
        return await self.repository.add_version(task_id, self._scope(), input)

    async def list_versions(self, task_id: UUID) -> list[WorkbenchTaskVersionRecord]:
        return await self.repository.list_versions(task_id, self._scope())

    async def select_version(self, task_id: UUID, version_id: UUID, selection: str) -> WorkbenchTaskVersionRecord:
        return await self.repository.select_version(task_id, self._scope(), version_id, selection)

    async def get_layout(self, project_id: UUID) -> WorkbenchLayoutRecord | None:
        return await self.repository.get_layout(project_id, self._scope())

    async def save_layout(self, project_id: UUID, expected_version: int, viewport: dict[str, Any], nodes: list[dict[str, Any]], groups: list[dict[str, Any]]) -> WorkbenchLayoutRecord:
        return await self.repository.save_layout(project_id, self._scope(), expected_version, viewport, nodes, groups)

    async def list_references(self, project_id: UUID, target_type: str | None = None, target_id: UUID | None = None) -> list[WorkbenchReferenceRecord]:
        return await self.repository.list_references(project_id, self._scope(), target_type, target_id)

    async def create_reference(self, project_id: UUID, target_type: str, target_id: UUID, resource_type: str, resource_id: UUID, resource_version: str, source_snapshot: dict[str, Any]):
        if target_type == "task":
            target = await self.get_task(target_id)
            if target is None or target.project_id != project_id:
                raise AppError("WORKBENCH_REFERENCE_SCOPE", "引用目标不属于当前项目", 409)
        elif target_type == "plan":
            if self.suite_planning_service is None:
                raise AppError("WORKBENCH_REFERENCE_SCOPE", "引用目标不属于当前项目", 409)
            try:
                plan = await self.suite_planning_service.get_plan(project_id, target_id)
            except AppError:
                raise AppError("WORKBENCH_REFERENCE_SCOPE", "引用目标不属于当前项目", 409) from None
            if getattr(getattr(plan, "plan", plan), "project_id", project_id) != project_id:
                raise AppError("WORKBENCH_REFERENCE_SCOPE", "引用目标不属于当前项目", 409)
        else:
            raise AppError("WORKBENCH_REFERENCE_INVALID", "引用目标类型无效", 400)
        if self.project_repository is not None and resource_type in {"project_asset", "input_image", "base_image"}:
            asset = await self.project_repository.get_asset(resource_id, self._scope())
            if asset is None or asset.project_id != project_id:
                raise AppError("WORKBENCH_REFERENCE_SCOPE", "引用资源不属于当前项目", 409)
        return await self.repository.create_reference(self._scope(), project_id, target_type, target_id, resource_type, resource_id, resource_version, source_snapshot)

    async def archive_reference(self, reference_id: UUID) -> WorkbenchReferenceRecord:
        return await self.repository.archive_reference(reference_id, self._scope())
