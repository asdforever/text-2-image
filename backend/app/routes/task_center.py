import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from ..core.http import success_response


task_center_router = APIRouter(prefix="/api/task-center")


def _error(record: Any) -> dict[str, str] | None:
    code = getattr(record, "error_code", None)
    message = getattr(record, "error_message", None)
    if not code and not message:
        return None
    return {
        "code": code or "TASK_FAILED",
        "message": message or code or "任务执行失败",
    }


def _progress(detail: Any) -> dict[str, int] | None:
    if detail is None or not hasattr(detail, "progress"):
        return None
    progress = detail.progress
    if progress is None:
        return None
    return {
        "succeeded": getattr(progress, "succeeded", 0),
        "total": getattr(progress, "total", 0),
        "failed": getattr(progress, "failed", 0),
        "cancelled": getattr(progress, "cancelled", 0),
    }


def _summary(*, project: Any, task_id: UUID, task_type: str, status: str,
             created_at: datetime, updated_at: datetime, progress: dict[str, int] | None,
             error: dict[str, str] | None, source: str) -> dict[str, Any]:
    return {
        "id": str(task_id),
        "projectId": str(project.id),
        "projectName": project.name,
        "type": task_type,
        "source": source,
        "status": status,
        "phase": status,
        "progress": progress,
        "createdAt": created_at.isoformat(),
        "updatedAt": updated_at.isoformat(),
        "error": error,
        "workbenchTab": "hero" if task_type == "hero" else "suite",
    }


async def _project_tasks(request: Request, project: Any, workspace_id: UUID) -> list[dict[str, Any]]:
    hero_repository = request.app.state.hero_generation_repository
    batch_repository = request.app.state.batch_generation_repository
    suite_repository = request.app.state.suite_planning_repository

    hero, hero_batch, suite_plan = await asyncio.gather(
        hero_repository.get_latest(project.id, workspace_id),
        batch_repository.get_latest(project.id, workspace_id, kind="hero"),
        suite_repository.get_latest(project.id, workspace_id),
    )
    candidates: list[dict[str, Any]] = []
    if hero is not None:
        candidates.append(_summary(
            project=project, task_id=hero.id, task_type="hero", status=hero.status,
            created_at=hero.created_at, updated_at=hero.updated_at, progress=None,
            error=_error(hero), source="hero_generation",
        ))
    if hero_batch is not None:
        detail = await batch_repository.get_batch_detail(hero_batch.id, workspace_id)
        candidates.append(_summary(
            project=project, task_id=hero_batch.id, task_type="hero", status=hero_batch.status,
            created_at=hero_batch.created_at, updated_at=hero_batch.updated_at,
            progress=_progress(detail), error=_error(hero_batch), source="generation_batch",
        ))
    if suite_plan is not None:
        suite_batch = None
        detail = None
        if suite_plan.plan.generation_batch_id:
            detail = await batch_repository.get_batch_detail(suite_plan.plan.generation_batch_id, workspace_id)
            suite_batch = detail.batch if detail is not None else None
        record = suite_batch or suite_plan.plan
        candidates.append(_summary(
            project=project, task_id=record.id, task_type="suite", status=record.status,
            created_at=record.created_at, updated_at=record.updated_at,
            progress=_progress(detail), error=_error(record), source="suite_generation" if suite_batch else "suite_plan",
        ))

    latest_by_type: dict[str, dict[str, Any]] = {}
    for item in candidates:
        previous = latest_by_type.get(item["type"])
        if previous is None or item["updatedAt"] >= previous["updatedAt"]:
            latest_by_type[item["type"]] = item
    return list(latest_by_type.values())


@task_center_router.get("")
async def list_task_center(request: Request):
    context = request.app.state.identity_provider.get_context()
    projects = await request.app.state.project_service.list_projects(include_archived=True)
    groups = []
    for project in projects:
        tasks = await _project_tasks(request, project, context.workspace_id)
        if tasks:
            groups.append({
                "projectId": str(project.id),
                "projectName": project.name,
                "projectStatus": project.status,
                "updatedAt": max(item["updatedAt"] for item in tasks),
                "tasks": sorted(tasks, key=lambda item: item["updatedAt"], reverse=True),
            })
    groups.sort(key=lambda item: item["updatedAt"], reverse=True)
    return success_response({"projects": groups})
