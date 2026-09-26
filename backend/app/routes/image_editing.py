from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request

from ..application.image_editing_service import ImageEditingService
from ..application.prompt_usage import require_image_prompt
from ..core.errors import AppError
from ..core.http import success_response


image_editing_router = APIRouter()


def _session_view(item: Any) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "workspaceId": str(item.workspace_id),
        "projectId": str(item.project_id),
        "sourceVersionId": str(item.source_version_id),
        "sourceSnapshot": item.source_snapshot,
        "operations": item.operations_snapshot,
        "revision": item.revision,
        "status": item.status,
        "archivedAt": item.archived_at.isoformat() if item.archived_at else None,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


def _task_view(item: Any) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "workspaceId": str(item.workspace_id),
        "projectId": str(item.project_id),
        "sessionId": str(item.session_id),
        "revision": item.revision,
        "status": item.status,
        "operations": item.operations_snapshot,
        "sourceSnapshot": item.source_snapshot,
        "promptSnapshot": item.prompt_snapshot,
        "configSnapshot": item.config_snapshot,
        "attempts": [{"id": str(a.id), "attemptNumber": a.attempt_number, "status": a.status, "error": a.error_message} for a in item.attempts],
        "currentVersionId": str(item.current_version_id) if item.current_version_id else None,
        "finalVersionId": str(item.final_version_id) if item.final_version_id else None,
        "createdAt": item.created_at.isoformat(),
    }


def _service(request: Request) -> ImageEditingService:
    return request.app.state.image_editing_service


async def _require_image_prompt_reference(request: Request, snapshot: dict[str, Any]) -> None:
    version_id = snapshot.get("promptVersionId")
    template_id = snapshot.get("promptTemplateId")
    if not version_id and not template_id:
        return  # Custom instructions have no marketplace reference.
    try:
        parsed_version_id = UUID(str(version_id))
        parsed_template_id = UUID(str(template_id)) if template_id else None
    except (TypeError, ValueError):
        raise AppError("IMAGE_PROMPT_VERSION_INVALID", "提示词版本引用无效", 400) from None
    version = await request.app.state.prompt_service.repository.get_version(parsed_version_id)
    if version is None or (parsed_template_id is not None and version.template_id != parsed_template_id):
        raise AppError("IMAGE_PROMPT_VERSION_INVALID", "提示词版本不存在或不属于所选模板", 400)
    require_image_prompt(version)


@image_editing_router.post(
    "/api/projects/{project_id}/assets/{asset_id}/white-background-generations",
    status_code=202,
)
async def generate_white_background(
    project_id: UUID,
    asset_id: UUID,
    payload: dict[str, Any],
    request: Request,
    background_tasks: BackgroundTasks,
) -> Any:
    """基于项目原图生成白底图，并将结果回写到同一项目。"""
    prompt_body = str(payload.get("promptBody") or "").strip()
    prompt_template_id = str(payload.get("promptTemplateId") or "").strip()
    prompt_version_id = str(payload.get("promptVersionId") or "").strip()
    if not prompt_body or not prompt_template_id or not prompt_version_id:
        raise AppError("WHITE_BACKGROUND_PROMPT_REQUIRED", "请选择可用的白底图提示词", 400)

    await _require_image_prompt_reference(request, payload)

    session = await _service(request).create_session(project_id, asset_id)
    task = await _service(request).submit_session(
        session.id,
        prompt_snapshot={
            "summary": prompt_body,
            "promptTemplateId": prompt_template_id,
            "promptVersionId": prompt_version_id,
        },
        config_snapshot={
            "outputKind": "white_background",
            "outputFilename": f"{session.source_snapshot['filename']}-白底图.png",
            "ratio": "1:1",
            "size": "标准 1K",
        },
        idempotency_key=request.headers.get("Idempotency-Key"),
    )
    background_tasks.add_task(request.app.state.image_editing_worker.process_task, task.id)
    return success_response(_task_view(task))


@image_editing_router.get("/api/projects/{project_id}/white-background-generations")
async def list_white_background_generations(project_id: UUID, request: Request) -> Any:
    service = _service(request)
    workspace_id = service._workspace_id()
    project = await service.project_repository.get_project(project_id, workspace_id)
    if project is None:
        raise AppError("IMAGE_EDIT_PROJECT_NOT_FOUND", "项目不存在", 404)
    tasks = await service.repository.list_tasks(project_id, workspace_id)
    return success_response([_task_view(task) for task in tasks
        if task.config_snapshot.get("outputKind") == "white_background" and task.status != "archived"])


@image_editing_router.get("/api/image-editor/capabilities")
async def capabilities() -> Any:
    return success_response(
        {
            "provider": {"name": "configured-image-editor", "version": "2", "capabilitiesVersion": "canvas-v2"},
            "capabilities": {"imageToImage": True, "currentVersionInput": False, "redraw": True, "erase": True, "outpaint": False, "addText": True, "changeText": True, "cropResize": True, "ocr": False},
        }
    )


@image_editing_router.post("/api/image-editor/sessions", status_code=201)
async def create_session(payload: dict[str, Any], request: Request) -> Any:
    try:
        project_id = UUID(str(payload.get("projectId")))
        source_version_id = UUID(str(payload.get("sourceVersionId")))
    except (TypeError, ValueError) as exc:
        raise AppError("INVALID_REQUEST", "项目或源图片版本标识无效", 400) from exc
    session = await _service(request).create_session(project_id, source_version_id)
    return success_response(_session_view(session))


@image_editing_router.get("/api/image-editor/sessions")
async def list_sessions(projectId: UUID, request: Request, includeArchived: bool = False) -> Any:
    sessions = await _service(request).list_sessions(projectId, include_archived=includeArchived)
    return success_response([_session_view(item) for item in sessions])


@image_editing_router.get("/api/image-editor/sessions/{session_id}")
async def get_session(session_id: UUID, request: Request) -> Any:
    session = await _service(request).get_session(session_id)
    if session is None:
        raise AppError("IMAGE_EDIT_SESSION_NOT_FOUND", "图片编辑会话不存在", 404)
    return success_response(_session_view(session))

@image_editing_router.post("/api/image-editor/sessions/{session_id}/archive")
async def archive_session(session_id: UUID, request: Request) -> Any:
    return success_response(_session_view(await _service(request).archive_session(session_id)))


@image_editing_router.post("/api/image-editor/sessions/{session_id}/operations")
async def save_operation(session_id: UUID, payload: dict[str, Any], request: Request) -> Any:
    service = _service(request)
    current = await service.get_session(session_id)
    if current is None:
        raise AppError("IMAGE_EDIT_SESSION_NOT_FOUND", "图片编辑会话不存在", 404)
    operation = payload.get("operation") if isinstance(payload.get("operation"), dict) else payload
    expected_revision = int(payload.get("expectedRevision", current.revision))
    updated = await service.add_operation(
        session_id, operation, expected_revision=expected_revision
    )
    return success_response(_session_view(updated))


@image_editing_router.delete("/api/image-editor/sessions/{session_id}/operations/{operation_id}")
async def delete_operation(session_id: UUID, operation_id: str, request: Request, expectedRevision: int | None = None) -> Any:
    service = _service(request)
    current = await service.get_session(session_id)
    if current is None:
        raise AppError("IMAGE_EDIT_SESSION_NOT_FOUND", "图片编辑会话不存在", 404)
    updated = await service.remove_operation(
        session_id,
        operation_id,
        expected_revision=current.revision if expectedRevision is None else expectedRevision,
    )
    return success_response(_session_view(updated))


@image_editing_router.post("/api/image-editor/sessions/{session_id}/ocr")
async def recognize_ocr(session_id: UUID, payload: dict[str, Any], request: Request) -> Any:
    try:
        source_version_id = UUID(str(payload.get("sourceVersionId")))
    except (TypeError, ValueError) as exc:
        raise AppError("INVALID_REQUEST", "源图片版本标识无效", 400) from exc
    result = await _service(request).recognize_ocr(
        session_id,
        source_version_id,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )
    return success_response(
        {
            "id": str(result.id),
            "sourceVersionId": str(result.source_version_id),
            "status": "succeeded",
            "text": result.text,
            "blocks": result.regions,
            "provider": result.provider_snapshot,
            "createdAt": result.created_at.isoformat(),
        }
    )


@image_editing_router.post("/api/image-editor/sessions/{session_id}/submit", status_code=202)
async def submit_session(session_id: UUID, payload: dict[str, Any], request: Request, background_tasks: BackgroundTasks) -> Any:
    prompt_snapshot = dict(payload.get("promptSnapshot") or {"summary": payload.get("summary", "")})
    await _require_image_prompt_reference(request, prompt_snapshot)
    task = await _service(request).submit_session(
        session_id,
        prompt_snapshot=prompt_snapshot,
        config_snapshot=dict(payload.get("configSnapshot") or payload.get("generationParams") or {}),
        idempotency_key=request.headers.get("Idempotency-Key"),
        regenerate_summary=payload.get("summary"),
    )
    if task.config_snapshot.get("outputKind") == "canvas_edit" and task.status == "queued":
        background_tasks.add_task(request.app.state.image_editing_worker.process_task, task.id)
    return success_response(_task_view(task))


@image_editing_router.get("/api/image-editor/tasks/{task_id}")
async def get_task(task_id: UUID, request: Request) -> Any:
    task = await _service(request).repository.get_task(task_id, _service(request)._workspace_id())
    if task is None:
        raise AppError("IMAGE_EDIT_TASK_NOT_FOUND", "图片编辑任务不存在", 404)
    return success_response(_task_view(task))


@image_editing_router.post("/api/image-editor/tasks/{task_id}/versions/{version_id}/select")
async def select_version(task_id: UUID, version_id: UUID, payload: dict[str, Any], request: Request) -> Any:
    version = await _service(request).select_version(task_id, version_id, str(payload.get("selection", "current")))
    return success_response({"id": str(version.id), "taskId": str(version.task_id), "versionNumber": version.version_number, "objectKey": version.object_key, "previewUrl": version.preview_url, "isCurrent": version.is_current, "isFinal": version.is_final})


@image_editing_router.post("/api/image-editor/attempts/{attempt_id}/retry")
async def retry_attempt(attempt_id: UUID, request: Request, background_tasks: BackgroundTasks) -> Any:
    task = await _service(request).retry_attempt(attempt_id)
    if task.config_snapshot.get("outputKind") == "canvas_edit":
        background_tasks.add_task(request.app.state.image_editing_worker.process_task, task.id)
    return success_response(_task_view(task))


@image_editing_router.post("/api/image-editor/tasks/{task_id}/regenerate")
async def regenerate_task(task_id: UUID, payload: dict[str, Any], request: Request, background_tasks: BackgroundTasks) -> Any:
    task = await _service(request).regenerate_task(task_id, payload.get("summary"))
    if task.config_snapshot.get("outputKind") == "canvas_edit":
        background_tasks.add_task(request.app.state.image_editing_worker.process_task, task.id)
    return success_response(_task_view(task))
