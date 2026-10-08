from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, Request

from ..application.workbench_service import WorkbenchService
from ..application.canvas_lineage import canvas_generation_steps, style_harmonization_steps, reverse_execution_steps
from ..core.errors import AppError
from ..application.idempotency import request_fingerprint
from ..core.http import success_response
from ..schemas import WorkbenchBatchGenerationInput, WorkbenchGenerationInput, WorkbenchLayoutInput, WorkbenchReferenceInput, WorkbenchTaskCreateInput, WorkbenchTaskPatchInput
from ..workbench_repository import WorkbenchTaskInput


workbench_router = APIRouter()


def _version_view(item) -> dict[str, Any]:
    return {"id": str(item.id), "taskId": str(item.task_id), "slotId": str(item.slot_id) if item.slot_id else "", "attemptId": str(item.attempt_id) if item.attempt_id else "", "versionNumber": item.version_number, "objectKey": item.object_key, "processObjectKeys": [], "previewUrl": item.preview_url, "sha256": "", "width": 1, "height": 1, "mimeType": "image/png", "promptSnapshot": item.prompt_snapshot, "contextSnapshot": item.context_snapshot, "isCurrent": item.is_current, "isFinal": item.is_final, "createdAt": item.created_at.isoformat()}


def _task_view(item, versions: list[Any] | None = None) -> dict[str, Any]:
    status = {"draft": "incomplete", "queued": "pending", "generating": "generating", "succeeded": "generated", "failed": "failed", "cancelled": "failed", "archived": "archived"}.get(item.status, item.status)
    return {"id": str(item.id), "suiteId": str(item.project_id), "planSnapshotId": str(item.plan_snapshot_id) if item.plan_snapshot_id else None, "planItemId": str(item.plan_item_id) if item.plan_item_id else None, "ordinal": item.ordinal, "imageType": item.image_type, "title": item.title, "purpose": item.purpose, "promptDraft": item.prompt_draft, "promptRevision": item.prompt_revision, "sourceInputImageId": str(item.source_input_image_id) if item.source_input_image_id else None, "generationParams": item.generation_params, "status": status, "currentVersionId": str(item.current_version_id) if item.current_version_id else None, "finalVersionId": str(item.final_version_id) if item.final_version_id else None, "archivedAt": item.archived_at.isoformat() if item.archived_at else None, "createdAt": item.created_at.isoformat(), "updatedAt": item.updated_at.isoformat(), "versions": [_version_view(version) for version in (versions or [])], "attempts": [], "slots": []}


def _layout_view(item) -> dict[str, Any] | None:
    if item is None:
        return None
    return {"id": str(item.id), "suiteId": str(item.project_id), "layoutVersion": item.layout_version, "viewport": item.viewport, "nodes": item.nodes, "groups": item.groups, "updatedAt": item.updated_at.isoformat()}


def _reference_view(item) -> dict[str, Any]:
    return {"id": str(item.id), "suiteId": str(item.project_id), "targetType": item.target_type, "targetId": str(item.target_id), "resourceType": item.resource_type, "resourceId": str(item.resource_id), "resourceVersion": item.resource_version, "resourceVersionId": item.resource_version, "sourceSnapshot": item.source_snapshot, "snapshot": item.source_snapshot, "createdBy": None, "archivedAt": item.archived_at.isoformat() if item.archived_at else None, "createdAt": item.created_at.isoformat()}


def _service(request: Request) -> WorkbenchService:
    return request.app.state.workbench_service


async def _run_idempotent(request: Request, idempotency_key: str | None, payload: dict[str, Any], action):
    if not idempotency_key:
        return success_response(await action())
    store = getattr(request.app.state, "idempotency_store", None)
    if store is None:
        return success_response(await action())
    workspace_id = request.app.state.identity_provider.get_context().workspace_id
    scope = f"workbench:{workspace_id}"
    fingerprint = request_fingerprint(payload)
    claim = await store.claim(scope, idempotency_key, fingerprint)
    if not claim.is_owner:
        if claim.record.status == "completed" and claim.record.response_body:
            return claim.record.response_body
        raise AppError("IDEMPOTENCY_REQUEST_IN_PROGRESS", "相同请求正在处理中，请稍后重试", 409)
    try:
        data = await action()
        response = success_response(data)
        await store.complete(scope, idempotency_key, fingerprint, response_status=200, response_body=response)
        return response
    except Exception:
        raise


@workbench_router.get("/api/suites/{suite_id}/workbench")
async def get_workbench(suite_id: UUID, request: Request):
    service = _service(request)
    aggregate = await service.get_workbench(suite_id)
    editing = request.app.state.image_editing_service
    children = []
    edit_tasks = await editing.repository.list_tasks(suite_id, service._scope())
    assets = await service.project_repository.list_assets(suite_id, service._scope()) if service.project_repository else []
    steps = await canvas_generation_steps(suite_id, service._scope(), assets, service.batch_repository, edit_tasks)
    # Legacy suite workbenches may predate the product-project domain. The
    # aggregate above owns validation; the projection query remains scoped.
    reverse_batches = await request.app.state.reverse_execution_batch_repository.list(service._scope(), suite_id)
    steps.extend(reverse_execution_steps(reverse_batches, assets))
    # 风格候选有独立任务快照，仅投影生成依据，不加入替换原图的版本轨道。
    if any((asset.source_snapshot or {}).get("styleHarmonizationId") for asset in assets if asset.state == "available"):
        jobs = await request.app.state.style_harmonization_service.list_jobs(suite_id)
        steps.extend(style_harmonization_steps(jobs, assets))
    tracks = await request.app.state.canvas_generation_service.recover_expired(suite_id)
    for task in edit_tasks:
        edit_versions = []
        for version in task.versions:
            preview_url = version.preview_url
            if preview_url.startswith(("http://", "https://")):
                preview_url = await request.app.state.project_asset_storage.preview_url(version.object_key)
            edit_versions.append({"id": str(version.id), "previewUrl": preview_url, "versionNumber": version.version_number, "width": version.source_snapshot.get("width", 1), "height": version.source_snapshot.get("height", 1), "mimeType": "image/png", "attemptId": str(version.attempt_id), "promptSnapshot": version.prompt_snapshot})
        children.append({
            "task": {"id": str(task.id), "summary": task.prompt_snapshot.get("summary", "图片编辑"), "sourceCardId": task.config_snapshot.get("sourceCardId"), "sourceVersionId": task.source_snapshot.get("assetId"), "status": task.status, "promptSnapshot": task.prompt_snapshot, "currentVersionId": str(task.current_version_id) if task.current_version_id else None, "finalVersionId": str(task.final_version_id) if task.final_version_id else None, "createdAt": task.created_at.isoformat()},
            "snapshot": {"sourceVersionId": task.source_snapshot.get("assetId"), "operations": task.operations_snapshot},
            "attempts": [{"id": str(attempt.id), "status": attempt.status, "errorMessage": attempt.error_message} for attempt in task.attempts],
            "versions": edit_versions,
        })
    return success_response({"suite": aggregate["suite"], "inputImages": aggregate["inputImages"], "planSnapshot": aggregate["planSnapshot"], "tasks": [_task_view(task, versions) for task, versions in aggregate["tasks"]], "batches": aggregate["batches"], "layout": _layout_view(aggregate["layout"]), "references": [_reference_view(item) for item in aggregate["references"]], "imageEditChildren": children, "generationSteps": steps, "generationTracks": tracks})


@workbench_router.post("/api/suites/{suite_id}/tasks", status_code=201)
async def create_tasks(suite_id: UUID, payload: WorkbenchTaskCreateInput, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    service = _service(request)
    async def action():
        if payload.tasks:
            items = [WorkbenchTaskInput(item.planItemId, item.ordinal, item.title, item.purpose, item.promptDraft, item.generationParams, item.imageType, item.sourceInputImageId) for item in payload.tasks]
            tasks, replay = await service.create_tasks(suite_id, payload.planSnapshotId, idempotency_key or "", items)
        else:
            tasks, replay = await service.create_tasks_from_plan(suite_id, payload.planSnapshotId, idempotency_key or "")
        return {"planSnapshotId": str(payload.planSnapshotId), "tasks": [_task_view(task) for task in tasks], "createdTaskIds": [str(task.id) for task in tasks], "duplicate": replay}
    return await _run_idempotent(request, idempotency_key, {"suiteId": str(suite_id), **payload.model_dump()}, action)


@workbench_router.patch("/api/suite-tasks/{task_id}")
async def update_task(task_id: UUID, payload: WorkbenchTaskPatchInput, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    raw = payload.model_dump(exclude_none=True)
    changes = {key: raw[key] for key in ("title", "purpose", "promptDraft", "sourceInputImageId", "generationParams") if key in raw}
    changes = {({"promptDraft": "prompt_draft", "sourceInputImageId": "source_input_image_id", "generationParams": "generation_params"}.get(key, key)): value for key, value in changes.items()}
    async def action():
        task = await _service(request).update_task(task_id, payload.expectedRevision, changes)
        return _task_view(task, await _service(request).list_versions(task.id))
    return await _run_idempotent(request, idempotency_key, {"taskId": str(task_id), **payload.model_dump()}, action)


def _batch_view(batch: Any) -> dict[str, Any]:
    return {"batchId": str(batch.id), "status": {"queued": "running", "compiling_prompt": "running", "awaiting_confirmation": "running"}.get(str(batch.status), str(batch.status))}


@workbench_router.post("/api/suite-tasks/{task_id}/generation")
async def start_task_generation(task_id: UUID, payload: WorkbenchGenerationInput, request: Request):
    service = _service(request)
    expected_revision = payload.expectedRevision
    if expected_revision is None:
        task = await service.get_task(task_id)
        if task is None:
            raise AppError("WORKBENCH_TASK_NOT_FOUND", "工作台任务不存在", 404)
        expected_revision = task.prompt_revision
    return await _run_idempotent(request, request.headers.get("Idempotency-Key"), {"taskId": str(task_id), **payload.model_dump()}, lambda: _batch_view_async(service, task_id, int(expected_revision)))


@workbench_router.post("/api/suite-tasks/{task_id}/archive")
async def archive_task(task_id: UUID, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return await _run_idempotent(request, idempotency_key, {"taskId": str(task_id), "action": "archive"}, lambda: _archive_task_view(_service(request), task_id))


async def _archive_task_view(service: WorkbenchService, task_id: UUID):
    return _task_view(await service.archive_task(task_id))


@workbench_router.post("/api/suites/{suite_id}/generation")
async def start_batch_generation(suite_id: UUID, payload: WorkbenchBatchGenerationInput, request: Request):
    task_ids = payload.taskIds
    service = _service(request)
    return await _run_idempotent(request, request.headers.get("Idempotency-Key"), {"suiteId": str(suite_id), **payload.model_dump()}, lambda: _batch_view_async(service, suite_id, task_ids, batch=True))


async def _batch_view_async(service: WorkbenchService, identifier: UUID, expected_or_ids: Any, *, batch: bool = False):
    value = await (service.start_batch_generation(identifier, expected_or_ids) if batch else service.start_task_generation(identifier, expected_or_ids))
    return _batch_view(value)


@workbench_router.get("/api/suite-tasks/{task_id}/versions")
async def list_task_versions(task_id: UUID, request: Request):
    versions = await _service(request).list_versions(task_id)
    return success_response({"versions": [_version_view(item) for item in versions], "attempts": []})


@workbench_router.post("/api/suite-tasks/{task_id}/versions/{version_id}/select")
async def select_task_version(task_id: UUID, version_id: UUID, payload: dict[str, Any], request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    selection = str(payload.get("selection", "current"))
    return await _run_idempotent(request, idempotency_key, {"taskId": str(task_id), "versionId": str(version_id), "selection": selection}, lambda: _select_version_view(_service(request), task_id, version_id, selection))


async def _select_version_view(service: WorkbenchService, task_id: UUID, version_id: UUID, selection: str):
    return _version_view(await service.select_version(task_id, version_id, selection))


@workbench_router.get("/api/suites/{suite_id}/workbench/layout")
async def get_layout(suite_id: UUID, request: Request):
    return success_response(_layout_view(await _service(request).get_layout(suite_id)))


@workbench_router.patch("/api/suites/{suite_id}/workbench/layout")
async def save_layout(suite_id: UUID, payload: WorkbenchLayoutInput, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return await _run_idempotent(request, idempotency_key, {"suiteId": str(suite_id), **payload.model_dump()}, lambda: _save_layout_view(_service(request), suite_id, payload))


async def _save_layout_view(service: WorkbenchService, suite_id: UUID, payload: WorkbenchLayoutInput):
    return _layout_view(await service.save_layout(suite_id, payload.layoutVersion, payload.viewport, payload.nodes, payload.groups))


@workbench_router.get("/api/suites/{suite_id}/library/references")
async def list_references(suite_id: UUID, request: Request, targetType: str | None = None, targetId: UUID | None = None):
    return success_response([_reference_view(item) for item in await _service(request).list_references(suite_id, targetType, targetId)])


@workbench_router.post("/api/suites/{suite_id}/library/references", status_code=201)
async def create_reference(suite_id: UUID, payload: WorkbenchReferenceInput, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    async def action():
        item, duplicate = await _service(request).create_reference(suite_id, payload.targetType, payload.targetId, payload.resourceType, payload.resourceId, payload.resourceVersion, payload.sourceSnapshot)
        return {**_reference_view(item), "duplicate": duplicate}
    return await _run_idempotent(request, idempotency_key, {"suiteId": str(suite_id), **payload.model_dump()}, action)


@workbench_router.delete("/api/suites/{suite_id}/library/references/{reference_id}")
async def archive_reference(suite_id: UUID, reference_id: UUID, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return await _run_idempotent(request, idempotency_key, {"suiteId": str(suite_id), "referenceId": str(reference_id)}, lambda: _archive_reference_view(_service(request), reference_id))


async def _archive_reference_view(service: WorkbenchService, reference_id: UUID):
    return _reference_view(await service.archive_reference(reference_id))
