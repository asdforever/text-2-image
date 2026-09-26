from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .core.errors import AppError


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class WorkbenchTaskInput:
    plan_item_id: UUID
    ordinal: int
    title: str
    purpose: str
    prompt_draft: str
    generation_params: dict[str, Any]
    image_type: str = "detail"
    source_input_image_id: UUID | None = None


@dataclass(frozen=True)
class WorkbenchVersionInput:
    object_key: str
    version_number: int
    preview_url: str = ""
    prompt_snapshot: dict[str, Any] = field(default_factory=dict)
    context_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkbenchTaskRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    plan_snapshot_id: UUID | None
    plan_item_id: UUID | None
    ordinal: int
    image_type: str
    title: str
    purpose: str
    prompt_draft: str
    prompt_revision: int
    source_input_image_id: UUID | None
    generation_params: dict[str, Any]
    status: str = "draft"
    current_version_id: UUID | None = None
    final_version_id: UUID | None = None
    archived_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class WorkbenchTaskVersionRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    task_id: UUID
    version_number: int
    object_key: str
    preview_url: str = ""
    prompt_snapshot: dict[str, Any] = field(default_factory=dict)
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    is_current: bool = False
    is_final: bool = False
    batch_id: UUID | None = None
    slot_id: UUID | None = None
    attempt_id: UUID | None = None
    created_at: datetime = field(default_factory=_now)


@dataclass
class WorkbenchLayoutRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    layout_version: int
    viewport: dict[str, Any]
    nodes: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    updated_at: datetime = field(default_factory=_now)


@dataclass
class WorkbenchReferenceRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    target_type: str
    target_id: UUID
    resource_type: str
    resource_id: UUID
    resource_version: str
    source_snapshot: dict[str, Any]
    archived_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)


class InMemoryWorkbenchRepository:
    def __init__(self, backing_store: dict[str, Any] | None = None) -> None:
        state = backing_store if backing_store is not None else {}
        self.tasks: dict[UUID, WorkbenchTaskRecord] = state.setdefault("workbench_tasks", {})
        self.versions: dict[UUID, WorkbenchTaskVersionRecord] = state.setdefault("workbench_task_versions", {})
        self.layouts: dict[UUID, WorkbenchLayoutRecord] = state.setdefault("workbench_layouts", {})
        self.references: dict[UUID, WorkbenchReferenceRecord] = state.setdefault("workbench_references", {})
        self.create_keys: dict[tuple[UUID, UUID, str], list[UUID]] = state.setdefault("workbench_create_keys", {})

    async def create_tasks(
        self,
        workspace_id: UUID,
        project_id: UUID,
        plan_snapshot_id: UUID,
        idempotency_key: str,
        inputs: list[WorkbenchTaskInput],
    ) -> tuple[list[WorkbenchTaskRecord], bool]:
        key = (workspace_id, plan_snapshot_id, idempotency_key)
        existing_ids = self.create_keys.get(key)
        if existing_ids is not None:
            return [deepcopy(self.tasks[item]) for item in existing_ids], True
        if not inputs:
            raise AppError("WORKBENCH_TASKS_INVALID", "工作台任务不能为空", 400)
        if any(item.ordinal <= 0 for item in inputs):
            raise AppError("WORKBENCH_TASKS_INVALID", "工作台任务顺序无效", 400)
        tasks: list[WorkbenchTaskRecord] = []
        for item in sorted(inputs, key=lambda value: value.ordinal):
            task = WorkbenchTaskRecord(
                id=uuid4(), workspace_id=workspace_id, project_id=project_id,
                plan_snapshot_id=plan_snapshot_id, plan_item_id=item.plan_item_id,
                ordinal=item.ordinal, image_type=item.image_type, title=item.title,
                purpose=item.purpose, prompt_draft=item.prompt_draft, prompt_revision=1,
                source_input_image_id=item.source_input_image_id,
                generation_params=deepcopy(item.generation_params),
            )
            self.tasks[task.id] = task
            tasks.append(task)
        self.create_keys[key] = [task.id for task in tasks]
        return deepcopy(tasks), False

    async def get_task(self, task_id: UUID, workspace_id: UUID) -> WorkbenchTaskRecord | None:
        task = self.tasks.get(task_id)
        return deepcopy(task) if task and task.workspace_id == workspace_id else None

    async def list_tasks(self, project_id: UUID, workspace_id: UUID, include_archived: bool = False) -> list[WorkbenchTaskRecord]:
        values = [task for task in self.tasks.values() if task.project_id == project_id and task.workspace_id == workspace_id and (include_archived or task.archived_at is None)]
        return deepcopy(sorted(values, key=lambda item: item.ordinal))

    async def update_task(self, task_id: UUID, workspace_id: UUID, expected_revision: int, changes: dict[str, Any]) -> WorkbenchTaskRecord:
        task = self.tasks.get(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise AppError("WORKBENCH_TASK_NOT_FOUND", "工作台任务不存在", 404)
        if task.prompt_revision != expected_revision:
            raise AppError("WORKBENCH_TASK_REVISION_CONFLICT", "任务已被其他编辑更新，请刷新后重试", 409)
        if task.archived_at is not None:
            raise AppError("WORKBENCH_TASK_ARCHIVED", "已归档任务不可编辑", 409)
        allowed = {"title", "purpose", "prompt_draft", "source_input_image_id", "generation_params"}
        for key, value in changes.items():
            if key in allowed:
                setattr(task, key, deepcopy(value))
        task.prompt_revision += 1
        task.updated_at = _now()
        return deepcopy(task)

    async def archive_task(self, task_id: UUID, workspace_id: UUID) -> WorkbenchTaskRecord:
        task = self.tasks.get(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise AppError("WORKBENCH_TASK_NOT_FOUND", "工作台任务不存在", 404)
        if task.archived_at is None:
            task.archived_at = _now()
            task.status = "archived"
            task.updated_at = task.archived_at
        return deepcopy(task)

    async def add_version(self, task_id: UUID, workspace_id: UUID, input: WorkbenchVersionInput) -> WorkbenchTaskVersionRecord:
        task = self.tasks.get(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise AppError("WORKBENCH_TASK_NOT_FOUND", "工作台任务不存在", 404)
        version = WorkbenchTaskVersionRecord(
            id=uuid4(), workspace_id=workspace_id, project_id=task.project_id, task_id=task_id,
            version_number=input.version_number, object_key=input.object_key, preview_url=input.preview_url,
            prompt_snapshot=deepcopy(input.prompt_snapshot), context_snapshot=deepcopy(input.context_snapshot),
        )
        self.versions[version.id] = version
        return deepcopy(version)

    async def list_versions(self, task_id: UUID, workspace_id: UUID) -> list[WorkbenchTaskVersionRecord]:
        task = await self.get_task(task_id, workspace_id)
        if task is None:
            raise AppError("WORKBENCH_TASK_NOT_FOUND", "工作台任务不存在", 404)
        return deepcopy(sorted((version for version in self.versions.values() if version.task_id == task_id), key=lambda item: item.version_number))

    async def select_version(self, task_id: UUID, workspace_id: UUID, version_id: UUID, selection: str) -> WorkbenchTaskVersionRecord:
        task = self.tasks.get(task_id)
        version = self.versions.get(version_id)
        if task is None or version is None or task.workspace_id != workspace_id or version.task_id != task_id:
            raise AppError("WORKBENCH_VERSION_NOT_FOUND", "任务版本不存在", 404)
        if selection not in {"current", "final"}:
            raise AppError("WORKBENCH_VERSION_SELECTION_INVALID", "版本选择类型无效", 400)
        for item in self.versions.values():
            if item.task_id == task_id:
                setattr(item, "is_current" if selection == "current" else "is_final", item.id == version_id)
        setattr(task, "current_version_id" if selection == "current" else "final_version_id", version_id)
        task.prompt_revision += 1
        task.updated_at = _now()
        return deepcopy(version)

    async def save_layout(self, project_id: UUID, workspace_id: UUID, expected_version: int, viewport: dict[str, Any], nodes: list[dict[str, Any]], groups: list[dict[str, Any]]) -> WorkbenchLayoutRecord:
        current = next((item for item in self.layouts.values() if item.project_id == project_id and item.workspace_id == workspace_id), None)
        if current is not None and current.layout_version != expected_version:
            raise AppError("WORKBENCH_LAYOUT_CONFLICT", "画布布局已被更新，请刷新后重试", 409)
        now = _now()
        if current is None:
            current = WorkbenchLayoutRecord(uuid4(), workspace_id, project_id, 1, deepcopy(viewport), deepcopy(nodes), deepcopy(groups), now)
            self.layouts[current.id] = current
        else:
            current.layout_version += 1
            current.viewport, current.nodes, current.groups, current.updated_at = deepcopy(viewport), deepcopy(nodes), deepcopy(groups), now
        return deepcopy(current)

    async def get_layout(self, project_id: UUID, workspace_id: UUID) -> WorkbenchLayoutRecord | None:
        current = next((item for item in self.layouts.values() if item.project_id == project_id and item.workspace_id == workspace_id), None)
        return deepcopy(current) if current else None

    async def create_reference(self, workspace_id: UUID, project_id: UUID, target_type: str, target_id: UUID, resource_type: str, resource_id: UUID, resource_version: str, source_snapshot: dict[str, Any]) -> tuple[WorkbenchReferenceRecord, bool]:
        existing = next((item for item in self.references.values() if item.project_id == project_id and item.target_type == target_type and item.target_id == target_id and item.resource_type == resource_type and item.resource_id == resource_id and item.resource_version == resource_version and item.archived_at is None), None)
        if existing is not None:
            return deepcopy(existing), True
        if target_type not in {"plan", "task"}:
            raise AppError("WORKBENCH_REFERENCE_INVALID", "引用目标类型无效", 400)
        reference = WorkbenchReferenceRecord(uuid4(), workspace_id, project_id, target_type, target_id, resource_type, resource_id, resource_version, deepcopy(source_snapshot))
        self.references[reference.id] = reference
        return deepcopy(reference), False

    async def list_references(self, project_id: UUID, workspace_id: UUID, target_type: str | None = None, target_id: UUID | None = None) -> list[WorkbenchReferenceRecord]:
        values = [item for item in self.references.values() if item.project_id == project_id and item.workspace_id == workspace_id and item.archived_at is None and (target_type is None or item.target_type == target_type) and (target_id is None or item.target_id == target_id)]
        return deepcopy(values)

    async def archive_reference(self, reference_id: UUID, workspace_id: UUID) -> WorkbenchReferenceRecord:
        reference = self.references.get(reference_id)
        if reference is None or reference.workspace_id != workspace_id:
            raise AppError("WORKBENCH_REFERENCE_NOT_FOUND", "工作台引用不存在", 404)
        reference.archived_at = _now()
        return deepcopy(reference)


class PostgresWorkbenchRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create_tasks(self, workspace_id: UUID, project_id: UUID, plan_snapshot_id: UUID, idempotency_key: str, inputs: list[WorkbenchTaskInput]) -> tuple[list[WorkbenchTaskRecord], bool]:
        if not inputs:
            raise AppError("WORKBENCH_TASKS_INVALID", "工作台任务不能为空", 400)
        async with self.sessions() as session, session.begin():
            existing = await session.execute(text(
                "SELECT * FROM project_workbench.workbench_tasks WHERE workspace_id=:workspace_id AND project_id=:project_id AND plan_snapshot_id=:plan_id ORDER BY ordinal"
            ), {"workspace_id": workspace_id, "project_id": project_id, "plan_id": plan_snapshot_id})
            rows = existing.mappings().all()
            if rows:
                return [_task_from_row(row) for row in rows], True
            created: list[WorkbenchTaskRecord] = []
            saw_conflict = False
            for item in sorted(inputs, key=lambda value: value.ordinal):
                task_id = uuid4()
                row = await session.execute(text(
                    "INSERT INTO project_workbench.workbench_tasks (id,workspace_id,project_id,plan_snapshot_id,plan_item_id,ordinal,image_type,title,purpose,prompt_draft,prompt_revision,source_input_image_id,generation_params,status) VALUES (:id,:workspace_id,:project_id,:plan_id,:item_id,:ordinal,:image_type,:title,:purpose,:prompt,1,:source_id,CAST(:params AS jsonb),'draft') ON CONFLICT (project_id,plan_snapshot_id,plan_item_id) DO NOTHING RETURNING *"
                ), {"id": task_id, "workspace_id": workspace_id, "project_id": project_id, "plan_id": plan_snapshot_id, "item_id": item.plan_item_id, "ordinal": item.ordinal, "image_type": item.image_type, "title": item.title, "purpose": item.purpose, "prompt": item.prompt_draft, "source_id": item.source_input_image_id, "params": json.dumps(item.generation_params, ensure_ascii=False)})
                value = row.mappings().first()
                if value is None:
                    saw_conflict = True
                else:
                    created.append(_task_from_row(value))
            if saw_conflict:
                refreshed = await session.execute(text(
                    "SELECT * FROM project_workbench.workbench_tasks WHERE workspace_id=:workspace_id AND project_id=:project_id AND plan_snapshot_id=:plan_id ORDER BY ordinal"
                ), {"workspace_id": workspace_id, "project_id": project_id, "plan_id": plan_snapshot_id})
                return [_task_from_row(row) for row in refreshed.mappings().all()], True
            return created, False

    async def get_task(self, task_id: UUID, workspace_id: UUID) -> WorkbenchTaskRecord | None:
        async with self.sessions() as session:
            row = await session.execute(text("SELECT * FROM project_workbench.workbench_tasks WHERE id=:id AND workspace_id=:workspace_id"), {"id": task_id, "workspace_id": workspace_id})
            value = row.mappings().first()
            return _task_from_row(value) if value else None

    async def list_tasks(self, project_id: UUID, workspace_id: UUID, include_archived: bool = False) -> list[WorkbenchTaskRecord]:
        archived = "" if include_archived else " AND archived_at IS NULL"
        async with self.sessions() as session:
            rows = await session.execute(text("SELECT * FROM project_workbench.workbench_tasks WHERE project_id=:project_id AND workspace_id=:workspace_id" + archived + " ORDER BY ordinal"), {"project_id": project_id, "workspace_id": workspace_id})
            return [_task_from_row(row) for row in rows.mappings().all()]

    async def update_task(self, task_id: UUID, workspace_id: UUID, expected_revision: int, changes: dict[str, Any]) -> WorkbenchTaskRecord:
        allowed = {"title", "purpose", "prompt_draft", "source_input_image_id", "generation_params"}
        filtered = {key: value for key, value in changes.items() if key in allowed}
        assignments: list[str] = []
        params: dict[str, Any] = {"id": task_id, "workspace_id": workspace_id, "expected_revision": expected_revision}
        for key, value in filtered.items():
            if key == "generation_params":
                assignments.append("generation_params=CAST(:generation_params AS jsonb)")
                params[key] = json.dumps(value, ensure_ascii=False)
            else:
                assignments.append(f"{key}=:{key}")
                params[key] = value
        if not assignments:
            assignments.append("updated_at=updated_at")
        row_sql = ", ".join(assignments)
        async with self.sessions() as session, session.begin():
            row = await session.execute(text(
                f"UPDATE project_workbench.workbench_tasks SET {row_sql}, prompt_revision=prompt_revision+1, updated_at=now() WHERE id=:id AND workspace_id=:workspace_id AND prompt_revision=:expected_revision AND archived_at IS NULL RETURNING *"
            ), params)
            value = row.mappings().first()
            if value is None:
                existing = await session.execute(text("SELECT id FROM project_workbench.workbench_tasks WHERE id=:id AND workspace_id=:workspace_id"), params)
                if existing.first() is None:
                    raise AppError("WORKBENCH_TASK_NOT_FOUND", "工作台任务不存在", 404)
                raise AppError("WORKBENCH_TASK_REVISION_CONFLICT", "任务已被其他编辑更新，请刷新后重试", 409)
            return _task_from_row(value)

    async def archive_task(self, task_id: UUID, workspace_id: UUID) -> WorkbenchTaskRecord:
        async with self.sessions() as session, session.begin():
            row = await session.execute(text("UPDATE project_workbench.workbench_tasks SET status='archived', archived_at=COALESCE(archived_at, now()), updated_at=now() WHERE id=:id AND workspace_id=:workspace_id RETURNING *"), {"id": task_id, "workspace_id": workspace_id})
            value = row.mappings().first()
            if value is None:
                raise AppError("WORKBENCH_TASK_NOT_FOUND", "工作台任务不存在", 404)
            return _task_from_row(value)

    async def add_version(self, task_id: UUID, workspace_id: UUID, input: WorkbenchVersionInput) -> WorkbenchTaskVersionRecord:
        async with self.sessions() as session, session.begin():
            task = await session.execute(text("SELECT project_id FROM project_workbench.workbench_tasks WHERE id=:id AND workspace_id=:workspace_id"), {"id": task_id, "workspace_id": workspace_id})
            task_row = task.mappings().first()
            if task_row is None:
                raise AppError("WORKBENCH_TASK_NOT_FOUND", "工作台任务不存在", 404)
            row = await session.execute(text(
                "INSERT INTO project_workbench.workbench_task_versions (id,workspace_id,project_id,task_id,version_number,object_key,preview_url,prompt_snapshot,context_snapshot) VALUES (:id,:workspace_id,:project_id,:task_id,:number,:object_key,:preview_url,CAST(:prompt AS jsonb),CAST(:context AS jsonb)) RETURNING *"
            ), {"id": uuid4(), "workspace_id": workspace_id, "project_id": task_row["project_id"], "task_id": task_id, "number": input.version_number, "object_key": input.object_key, "preview_url": input.preview_url, "prompt": json.dumps(input.prompt_snapshot, ensure_ascii=False), "context": json.dumps(input.context_snapshot, ensure_ascii=False)})
            return _version_from_row(row.mappings().one())

    async def list_versions(self, task_id: UUID, workspace_id: UUID) -> list[WorkbenchTaskVersionRecord]:
        async with self.sessions() as session:
            rows = await session.execute(text("SELECT version.* FROM project_workbench.workbench_task_versions version JOIN project_workbench.workbench_tasks task ON task.id=version.task_id WHERE version.task_id=:task_id AND task.workspace_id=:workspace_id ORDER BY version.version_number"), {"task_id": task_id, "workspace_id": workspace_id})
            return [_version_from_row(row) for row in rows.mappings().all()]

    async def select_version(self, task_id: UUID, workspace_id: UUID, version_id: UUID, selection: str) -> WorkbenchTaskVersionRecord:
        if selection not in {"current", "final"}:
            raise AppError("WORKBENCH_VERSION_SELECTION_INVALID", "版本选择类型无效", 400)
        flag = "is_current" if selection == "current" else "is_final"
        pointer = "current_version_id" if selection == "current" else "final_version_id"
        async with self.sessions() as session, session.begin():
            target = await session.execute(text("SELECT version.* FROM project_workbench.workbench_task_versions version JOIN project_workbench.workbench_tasks task ON task.id=version.task_id WHERE version.id=:version_id AND version.task_id=:task_id AND task.workspace_id=:workspace_id FOR UPDATE"), {"version_id": version_id, "task_id": task_id, "workspace_id": workspace_id})
            value = target.mappings().first()
            if value is None:
                raise AppError("WORKBENCH_VERSION_NOT_FOUND", "任务版本不存在", 404)
            await session.execute(text(f"UPDATE project_workbench.workbench_task_versions SET {flag}=(id=:version_id) WHERE task_id=:task_id"), {"version_id": version_id, "task_id": task_id})
            await session.execute(text(f"UPDATE project_workbench.workbench_tasks SET {pointer}=:version_id, prompt_revision=prompt_revision+1, updated_at=now() WHERE id=:task_id AND workspace_id=:workspace_id"), {"version_id": version_id, "task_id": task_id, "workspace_id": workspace_id})
            return _version_from_row({**value, flag: True})

    async def save_layout(self, project_id: UUID, workspace_id: UUID, expected_version: int, viewport: dict[str, Any], nodes: list[dict[str, Any]], groups: list[dict[str, Any]]) -> WorkbenchLayoutRecord:
        payload = {"project_id": project_id, "workspace_id": workspace_id, "expected_version": expected_version, "viewport": json.dumps(viewport, ensure_ascii=False), "nodes": json.dumps(nodes, ensure_ascii=False), "groups": json.dumps(groups, ensure_ascii=False)}
        async with self.sessions() as session, session.begin():
            if expected_version == 0:
                row = await session.execute(text("INSERT INTO project_workbench.workbench_layouts (id,workspace_id,project_id,layout_version,viewport,nodes,groups) VALUES (:id,:workspace_id,:project_id,1,CAST(:viewport AS jsonb),CAST(:nodes AS jsonb),CAST(:groups AS jsonb)) ON CONFLICT (project_id) DO NOTHING RETURNING *"), {**payload, "id": uuid4()})
                value = row.mappings().first()
                if value is None:
                    raise AppError("WORKBENCH_LAYOUT_CONFLICT", "画布布局已被更新，请刷新后重试", 409)
            else:
                row = await session.execute(text("UPDATE project_workbench.workbench_layouts SET layout_version=layout_version+1, viewport=CAST(:viewport AS jsonb), nodes=CAST(:nodes AS jsonb), groups=CAST(:groups AS jsonb), updated_at=now() WHERE project_id=:project_id AND workspace_id=:workspace_id AND layout_version=:expected_version RETURNING *"), payload)
                value = row.mappings().first()
            if value is None:
                raise AppError("WORKBENCH_LAYOUT_CONFLICT", "画布布局已被更新，请刷新后重试", 409)
            return _layout_from_row(value)

    async def get_layout(self, project_id: UUID, workspace_id: UUID) -> WorkbenchLayoutRecord | None:
        async with self.sessions() as session:
            row = await session.execute(text("SELECT * FROM project_workbench.workbench_layouts WHERE project_id=:project_id AND workspace_id=:workspace_id"), {"project_id": project_id, "workspace_id": workspace_id})
            value = row.mappings().first()
            return _layout_from_row(value) if value else None

    async def create_reference(self, workspace_id: UUID, project_id: UUID, target_type: str, target_id: UUID, resource_type: str, resource_id: UUID, resource_version: str, source_snapshot: dict[str, Any]) -> tuple[WorkbenchReferenceRecord, bool]:
        params = {"id": uuid4(), "workspace_id": workspace_id, "project_id": project_id, "target_type": target_type, "target_id": target_id, "resource_type": resource_type, "resource_id": resource_id, "resource_version": resource_version, "snapshot": json.dumps(source_snapshot, ensure_ascii=False)}
        async with self.sessions() as session, session.begin():
            row = await session.execute(text("INSERT INTO project_workbench.workbench_references (id,workspace_id,project_id,target_type,target_id,resource_type,resource_id,resource_version,source_snapshot) VALUES (:id,:workspace_id,:project_id,:target_type,:target_id,:resource_type,:resource_id,:resource_version,CAST(:snapshot AS jsonb)) ON CONFLICT (project_id,target_type,target_id,resource_type,resource_id,resource_version) DO NOTHING RETURNING *"), params)
            value = row.mappings().first()
            if value is not None:
                return _reference_from_row(value), False
            existing = await session.execute(text("SELECT * FROM project_workbench.workbench_references WHERE project_id=:project_id AND target_type=:target_type AND target_id=:target_id AND resource_type=:resource_type AND resource_id=:resource_id AND resource_version=:resource_version"), params)
            return _reference_from_row(existing.mappings().one()), True

    async def list_references(self, project_id: UUID, workspace_id: UUID, target_type: str | None = None, target_id: UUID | None = None) -> list[WorkbenchReferenceRecord]:
        conditions = ["project_id=:project_id", "workspace_id=:workspace_id", "archived_at IS NULL"]
        params: dict[str, Any] = {"project_id": project_id, "workspace_id": workspace_id}
        if target_type:
            conditions.append("target_type=:target_type"); params["target_type"] = target_type
        if target_id:
            conditions.append("target_id=:target_id"); params["target_id"] = target_id
        async with self.sessions() as session:
            rows = await session.execute(text("SELECT * FROM project_workbench.workbench_references WHERE " + " AND ".join(conditions) + " ORDER BY created_at"), params)
            return [_reference_from_row(row) for row in rows.mappings().all()]

    async def archive_reference(self, reference_id: UUID, workspace_id: UUID) -> WorkbenchReferenceRecord:
        async with self.sessions() as session, session.begin():
            row = await session.execute(text("UPDATE project_workbench.workbench_references SET archived_at=now() WHERE id=:id AND workspace_id=:workspace_id RETURNING *"), {"id": reference_id, "workspace_id": workspace_id})
            value = row.mappings().first()
            if value is None:
                raise AppError("WORKBENCH_REFERENCE_NOT_FOUND", "工作台引用不存在", 404)
            return _reference_from_row(value)

    async def ready(self) -> bool:
        try:
            async with self.sessions() as session:
                return bool(await session.scalar(text("SELECT to_regclass('project_workbench.workbench_tasks') IS NOT NULL")))
        except Exception:
            return False


def _json(value: Any, fallback: Any) -> Any:
    if value is None:
        return deepcopy(fallback)
    if isinstance(value, str):
        return json.loads(value)
    return deepcopy(value)


def _task_from_row(row: Any) -> WorkbenchTaskRecord:
    return WorkbenchTaskRecord(row["id"], row["workspace_id"], row["project_id"], row["plan_snapshot_id"], row["plan_item_id"], row["ordinal"], row["image_type"], row["title"], row["purpose"], row["prompt_draft"], row["prompt_revision"], row["source_input_image_id"], _json(row["generation_params"], {}), row["status"], row["current_version_id"], row["final_version_id"], row["archived_at"], row["created_at"], row["updated_at"])


def _version_from_row(row: Any) -> WorkbenchTaskVersionRecord:
    return WorkbenchTaskVersionRecord(row["id"], row["workspace_id"], row["project_id"], row["task_id"], row["version_number"], row["object_key"], row["preview_url"], _json(row["prompt_snapshot"], {}), _json(row["context_snapshot"], {}), row["is_current"], row["is_final"], row["batch_id"], row["slot_id"], row["attempt_id"], row["created_at"])


def _layout_from_row(row: Any) -> WorkbenchLayoutRecord:
    return WorkbenchLayoutRecord(row["id"], row["workspace_id"], row["project_id"], row["layout_version"], _json(row["viewport"], {}), _json(row["nodes"], []), _json(row["groups"], []), row["updated_at"])


def _reference_from_row(row: Any) -> WorkbenchReferenceRecord:
    return WorkbenchReferenceRecord(row["id"], row["workspace_id"], row["project_id"], row["target_type"], row["target_id"], row["resource_type"], row["resource_id"], row["resource_version"], _json(row["source_snapshot"], {}), row["archived_at"], row["created_at"])
