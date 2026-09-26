"""图片编辑域的仓储实现。

- `InMemoryImageEditingRepository`：无数据库时的契约测试替身。
- `PostgresImageEditingRepository`：把会话、任务、尝试、版本和 OCR 结果持久化到
  `project_workbench.image_edit_*` 表。

两个实现暴露同一组方法签名，`ImageEditingService` 与 `ImageEditingWorker` 不感知差异。
"""

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


@dataclass
class ImageEditSessionRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    source_version_id: UUID
    source_snapshot: dict[str, Any] = field(default_factory=dict)
    operations_snapshot: list[dict[str, Any]] = field(default_factory=list)
    revision: int = 1
    status: str = "draft"
    archived_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class ImageEditAttemptRecord:
    id: UUID
    task_id: UUID
    attempt_number: int = 1
    status: str = "queued"
    error_message: str | None = None


@dataclass
class ImageEditVersionRecord:
    id: UUID
    task_id: UUID
    attempt_id: UUID
    version_number: int
    object_key: str
    preview_url: str
    source_snapshot: dict[str, Any] = field(default_factory=dict)
    prompt_snapshot: dict[str, Any] = field(default_factory=dict)
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    is_current: bool = False
    is_final: bool = False
    created_at: datetime = field(default_factory=_now)


@dataclass
class ImageEditTaskRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    session_id: UUID
    revision: int = 1
    status: str = "queued"
    operations_snapshot: list[dict[str, Any]] = field(default_factory=list)
    source_snapshot: dict[str, Any] = field(default_factory=dict)
    prompt_snapshot: dict[str, Any] = field(default_factory=dict)
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    attempts: list[ImageEditAttemptRecord] = field(default_factory=list)
    versions: list[Any] = field(default_factory=list)
    current_version_id: UUID | None = None
    final_version_id: UUID | None = None
    created_at: datetime = field(default_factory=_now)


class ImageEditRevisionConflict(Exception):
    def __init__(self, current: ImageEditSessionRecord) -> None:
        self.current = current


def _merge_operation(
    operations: list[dict[str, Any]], operation: dict[str, Any]
) -> list[dict[str, Any]]:
    """按 operationId 覆盖后按 ordinal 重排并补全序号，与内存实现语义一致。"""
    operation_id = str(operation.get("operationId") or operation.get("id") or uuid4())
    normalized = dict(operation)
    normalized["operationId"] = operation_id
    merged = [
        dict(item)
        for item in operations
        if str(item.get("operationId")) != operation_id
    ]
    merged.append(normalized)
    merged.sort(key=lambda item: int(item.get("ordinal", 0)))
    for index, item in enumerate(merged, start=1):
        item.setdefault("ordinal", index)
    return merged


class InMemoryImageEditingRepository:
    def __init__(self, backing_store: dict[str, Any] | None = None) -> None:
        state = backing_store if backing_store is not None else {}
        self.sessions: dict[UUID, ImageEditSessionRecord] = state.setdefault("image_edit_sessions", {})
        self.ocr_results: dict[tuple[UUID, UUID, str], Any] = state.setdefault("image_edit_ocr_results", {})
        self.tasks: dict[UUID, ImageEditTaskRecord] = state.setdefault("image_edit_tasks", {})
        self.submit_keys: dict[tuple[UUID, str], UUID] = state.setdefault("image_edit_submit_keys", {})

    async def create_session(
        self,
        workspace_id: UUID,
        project_id: UUID,
        source_version_id: UUID,
        source_snapshot: dict[str, Any],
    ) -> ImageEditSessionRecord:
        record = ImageEditSessionRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            source_version_id=source_version_id,
            source_snapshot=dict(source_snapshot),
        )
        self.sessions[record.id] = record
        return record

    async def get_session(self, session_id: UUID, workspace_id: UUID) -> ImageEditSessionRecord | None:
        record = self.sessions.get(session_id)
        if record is None or record.workspace_id != workspace_id:
            return None
        return record

    async def list_sessions(
        self,
        project_id: UUID,
        workspace_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ImageEditSessionRecord]:
        records = [
            item
            for item in self.sessions.values()
            if item.project_id == project_id and item.workspace_id == workspace_id
        ]
        if not include_archived:
            records = [item for item in records if item.archived_at is None]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    async def save_operation(
        self,
        session_id: UUID,
        workspace_id: UUID,
        operation: dict[str, Any],
        expected_revision: int,
    ) -> ImageEditSessionRecord:
        session = await self.get_session(session_id, workspace_id)
        if session is None:
            return None  # type: ignore[return-value]
        if session.revision != expected_revision:
            raise ImageEditRevisionConflict(session)
        session.operations_snapshot = _merge_operation(session.operations_snapshot, operation)
        session.revision += 1
        session.updated_at = _now()
        return session

    async def remove_operation(
        self,
        session_id: UUID,
        workspace_id: UUID,
        operation_id: str,
        expected_revision: int,
    ) -> ImageEditSessionRecord:
        session = await self.get_session(session_id, workspace_id)
        if session is None:
            return None  # type: ignore[return-value]
        if session.revision != expected_revision:
            raise ImageEditRevisionConflict(session)
        session.operations_snapshot = [
            item for item in session.operations_snapshot if str(item.get("operationId")) != operation_id
        ]
        session.revision += 1
        session.updated_at = _now()
        return session

    async def get_ocr_result(self, session_id: UUID, source_version_id: UUID, fingerprint: str) -> Any | None:
        return self.ocr_results.get((session_id, source_version_id, fingerprint))

    async def save_ocr_result(self, result: Any) -> Any:
        self.ocr_results[(result.session_id, result.source_version_id, result.request_fingerprint)] = result
        return result

    async def create_task(
        self,
        session: ImageEditSessionRecord,
        prompt_snapshot: dict[str, Any],
        config_snapshot: dict[str, Any],
        idempotency_key: str | None,
    ) -> ImageEditTaskRecord:
        if idempotency_key:
            existing_id = self.submit_keys.get((session.id, idempotency_key))
            if existing_id is not None:
                return self.tasks[existing_id]
        task = ImageEditTaskRecord(
            id=uuid4(),
            workspace_id=session.workspace_id,
            project_id=session.project_id,
            session_id=session.id,
            operations_snapshot=[dict(item) for item in session.operations_snapshot],
            source_snapshot=dict(session.source_snapshot),
            prompt_snapshot=dict(prompt_snapshot),
            config_snapshot=dict(config_snapshot),
            attempts=[ImageEditAttemptRecord(uuid4(), UUID(int=0))],
        )
        task.attempts[0].task_id = task.id
        self.tasks[task.id] = task
        if idempotency_key:
            self.submit_keys[(session.id, idempotency_key)] = task.id
        session.status = "submitted"
        session.updated_at = _now()
        return task

    async def get_task(self, task_id: UUID, workspace_id: UUID) -> ImageEditTaskRecord | None:
        task = self.tasks.get(task_id)
        return task if task is not None and task.workspace_id == workspace_id else None

    async def list_tasks(self, project_id: UUID, workspace_id: UUID) -> list[ImageEditTaskRecord]:
        return sorted(
            (task for task in self.tasks.values() if task.project_id == project_id and task.workspace_id == workspace_id),
            key=lambda task: task.created_at,
        )

    async def claim_attempt(self, task_id: UUID, attempt_id: UUID, workspace_id: UUID) -> bool:
        task = await self.get_task(task_id, workspace_id)
        attempt = next((item for item in task.attempts if item.id == attempt_id), None) if task else None
        if attempt is None or attempt.status != "queued":
            return False
        attempt.status = "generating"
        task.status = "generating"
        return True

    async def complete_attempt(self, task_id: UUID, attempt_id: UUID, *, success: bool, error: str | None = None) -> None:
        task = self.tasks[task_id]
        attempt = next(item for item in task.attempts if item.id == attempt_id)
        attempt.status = "succeeded" if success else "failed"
        attempt.error_message = error
        task.status = "succeeded" if success else "failed"

    async def add_version(self, task_id: UUID, version: Any) -> Any:
        task = self.tasks[task_id]
        task.versions.append(version)
        task.current_version_id = version.id
        version.is_current = True
        return version

    async def retry_attempt(self, attempt_id: UUID, workspace_id: UUID) -> ImageEditTaskRecord | None:
        for task in self.tasks.values():
            if task.workspace_id != workspace_id:
                continue
            if any(attempt.id == attempt_id and attempt.status == "failed" for attempt in task.attempts):
                next_number = max(item.attempt_number for item in task.attempts) + 1
                task.attempts.append(ImageEditAttemptRecord(uuid4(), task.id, next_number, "queued"))
                task.status = "queued"
                return task
        return None

    async def select_version(self, task_id: UUID, version_id: UUID, workspace_id: UUID, selection: str) -> Any:
        task = await self.get_task(task_id, workspace_id)
        if task is None:
            return None
        version = next((item for item in task.versions if item.id == version_id), None)
        if version is None or not version.is_current:
            raise ValueError("incomplete")
        for item in task.versions:
            if selection == "final": item.is_final = item.id == version_id
            elif selection == "current": item.is_current = item.id == version_id
        if selection == "final": task.final_version_id = version_id
        else: task.current_version_id = version_id
        return version

    async def archive_session(self, session_id: UUID, workspace_id: UUID) -> ImageEditSessionRecord | None:
        session = await self.get_session(session_id, workspace_id)
        if session is None: return None
        session.status = "archived"; session.archived_at = _now(); session.updated_at = _now(); return session

    async def ready(self) -> bool:
        return True


class PostgresImageEditingRepository:
    """`image_edit_*` 表的持久化实现。

    `image_edit_sessions.operations_snapshot` 是编辑草稿的权威副本（与内存实现语义
    完全一致），同一事务内镜像写入规范化的 `image_edit_operations` 表，便于按操作查询。
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create_session(
        self,
        workspace_id: UUID,
        project_id: UUID,
        source_version_id: UUID,
        source_snapshot: dict[str, Any],
    ) -> ImageEditSessionRecord:
        async with self.sessions() as db, db.begin():
            row = await db.execute(
                text(
                    "INSERT INTO project_workbench.image_edit_sessions "
                    "(id, workspace_id, project_id, source_version_id, source_snapshot) "
                    "VALUES (:id, :workspace_id, :project_id, :source_version_id, "
                    "CAST(:source_snapshot AS jsonb)) "
                    f"RETURNING {_SESSION_COLUMNS}"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "source_version_id": source_version_id,
                    "source_snapshot": _dump(source_snapshot),
                },
            )
            return _session_from_row(row.mappings().one())

    async def get_session(self, session_id: UUID, workspace_id: UUID) -> ImageEditSessionRecord | None:
        async with self.sessions() as db:
            row = await db.execute(
                text(
                    f"SELECT {_SESSION_COLUMNS} FROM project_workbench.image_edit_sessions "
                    "WHERE id=:id AND workspace_id=:workspace_id"
                ),
                {"id": session_id, "workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _session_from_row(result) if result is not None else None

    async def list_sessions(
        self,
        project_id: UUID,
        workspace_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[ImageEditSessionRecord]:
        archived_clause = "" if include_archived else " AND archived_at IS NULL"
        async with self.sessions() as db:
            rows = await db.execute(
                text(
                    f"SELECT {_SESSION_COLUMNS} FROM project_workbench.image_edit_sessions "
                    "WHERE project_id=:project_id AND workspace_id=:workspace_id"
                    f"{archived_clause} ORDER BY updated_at DESC"
                ),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
            return [_session_from_row(row) for row in rows.mappings()]

    async def save_operation(
        self,
        session_id: UUID,
        workspace_id: UUID,
        operation: dict[str, Any],
        expected_revision: int,
    ) -> ImageEditSessionRecord:
        async with self.sessions() as db, db.begin():
            current = await _lock_session(db, session_id, workspace_id)
            if current is None:
                return None  # type: ignore[return-value]
            if current.revision != expected_revision:
                raise ImageEditRevisionConflict(current)
            return await _write_operations(
                db, current, _merge_operation(current.operations_snapshot, operation)
            )

    async def remove_operation(
        self,
        session_id: UUID,
        workspace_id: UUID,
        operation_id: str,
        expected_revision: int,
    ) -> ImageEditSessionRecord:
        async with self.sessions() as db, db.begin():
            current = await _lock_session(db, session_id, workspace_id)
            if current is None:
                return None  # type: ignore[return-value]
            if current.revision != expected_revision:
                raise ImageEditRevisionConflict(current)
            remaining = [
                dict(item)
                for item in current.operations_snapshot
                if str(item.get("operationId")) != operation_id
            ]
            return await _write_operations(db, current, remaining)

    async def get_ocr_result(
        self, session_id: UUID, source_version_id: UUID, fingerprint: str
    ) -> Any | None:
        async with self.sessions() as db:
            row = await db.execute(
                text(
                    f"SELECT {_OCR_COLUMNS} FROM project_workbench.image_ocr_results "
                    "WHERE session_id=:session_id AND source_version_id=:source_version_id "
                    "AND request_fingerprint=:fingerprint"
                ),
                {
                    "session_id": session_id,
                    "source_version_id": source_version_id,
                    "fingerprint": fingerprint,
                },
            )
            result = row.mappings().first()
            return _ocr_from_row(result) if result is not None else None

    async def save_ocr_result(self, result: Any) -> Any:
        params = {
            "id": result.id,
            "workspace_id": result.workspace_id,
            "project_id": result.project_id,
            "session_id": result.session_id,
            "source_version_id": result.source_version_id,
            "request_fingerprint": result.request_fingerprint,
            "text": result.text,
            "regions": _dump(result.regions),
            "provider_snapshot": _dump(result.provider_snapshot),
            "created_at": result.created_at,
        }
        async with self.sessions() as db, db.begin():
            row = await db.execute(
                text(
                    "INSERT INTO project_workbench.image_ocr_results "
                    "(id, workspace_id, project_id, session_id, source_version_id, "
                    "request_fingerprint, text, regions, provider_snapshot, created_at) "
                    "VALUES (:id, :workspace_id, :project_id, :session_id, :source_version_id, "
                    ":request_fingerprint, :text, CAST(:regions AS jsonb), "
                    "CAST(:provider_snapshot AS jsonb), :created_at) "
                    "ON CONFLICT (session_id, source_version_id, request_fingerprint) DO NOTHING "
                    f"RETURNING {_OCR_COLUMNS}"
                ),
                params,
            )
            saved = row.mappings().first()
            if saved is not None:
                return _ocr_from_row(saved)
            existing = await db.execute(
                text(
                    f"SELECT {_OCR_COLUMNS} FROM project_workbench.image_ocr_results "
                    "WHERE session_id=:session_id AND source_version_id=:source_version_id "
                    "AND request_fingerprint=:request_fingerprint"
                ),
                params,
            )
            return _ocr_from_row(existing.mappings().one())

    async def create_task(
        self,
        session: ImageEditSessionRecord,
        prompt_snapshot: dict[str, Any],
        config_snapshot: dict[str, Any],
        idempotency_key: str | None,
    ) -> ImageEditTaskRecord:
        async with self.sessions() as db, db.begin():
            row = await db.execute(
                text(
                    "INSERT INTO project_workbench.image_edit_tasks "
                    "(id, workspace_id, project_id, session_id, operations_snapshot, "
                    "source_snapshot, prompt_snapshot, config_snapshot, submit_idempotency_key) "
                    "VALUES (:id, :workspace_id, :project_id, :session_id, "
                    "CAST(:operations AS jsonb), CAST(:source AS jsonb), CAST(:prompt AS jsonb), "
                    "CAST(:config AS jsonb), :idempotency_key) "
                    "ON CONFLICT (session_id, submit_idempotency_key) DO NOTHING "
                    f"RETURNING {_TASK_COLUMNS}"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": session.workspace_id,
                    "project_id": session.project_id,
                    "session_id": session.id,
                    "operations": _dump(session.operations_snapshot),
                    "source": _dump(session.source_snapshot),
                    "prompt": _dump(prompt_snapshot),
                    "config": _dump(config_snapshot),
                    "idempotency_key": idempotency_key,
                },
            )
            created = row.mappings().first()
            if created is None:
                return await self._task_by_submit_key(db, session.id, idempotency_key)

            await db.execute(
                text(
                    "INSERT INTO project_workbench.image_edit_attempts "
                    "(id, workspace_id, project_id, task_id, attempt_number) "
                    "VALUES (:id, :workspace_id, :project_id, :task_id, 1)"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": session.workspace_id,
                    "project_id": session.project_id,
                    "task_id": created["id"],
                },
            )
            await db.execute(
                text(
                    "UPDATE project_workbench.image_edit_sessions "
                    "SET status='submitted', updated_at=now() WHERE id=:id"
                ),
                {"id": session.id},
            )
            return await self._load_task(db, created["id"])

    async def get_task(self, task_id: UUID, workspace_id: UUID) -> ImageEditTaskRecord | None:
        async with self.sessions() as db:
            row = await db.execute(
                text(
                    f"SELECT {_TASK_COLUMNS} FROM project_workbench.image_edit_tasks "
                    "WHERE id=:id AND workspace_id=:workspace_id"
                ),
                {"id": task_id, "workspace_id": workspace_id},
            )
            if row.mappings().first() is None:
                return None
            return await self._load_task(db, task_id)

    async def list_tasks(self, project_id: UUID, workspace_id: UUID) -> list[ImageEditTaskRecord]:
        async with self.sessions() as db:
            rows = await db.execute(
                text("SELECT id FROM project_workbench.image_edit_tasks WHERE project_id=:project_id AND workspace_id=:workspace_id ORDER BY created_at"),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
            return [await self._load_task(db, row.id) for row in rows]

    async def claim_attempt(self, task_id: UUID, attempt_id: UUID, workspace_id: UUID) -> bool:
        async with self.sessions() as db, db.begin():
            claimed = await db.execute(
                text("UPDATE project_workbench.image_edit_attempts SET status='generating' WHERE id=:id AND task_id=:task AND workspace_id=:workspace AND status='queued' RETURNING id"),
                {"id": attempt_id, "task": task_id, "workspace": workspace_id},
            )
            if claimed.first() is None:
                return False
            await db.execute(text("UPDATE project_workbench.image_edit_tasks SET status='generating', updated_at=now() WHERE id=:id AND workspace_id=:workspace"), {"id": task_id, "workspace": workspace_id})
            return True

    async def complete_attempt(
        self, task_id: UUID, attempt_id: UUID, *, success: bool, error: str | None = None
    ) -> None:
        status = "succeeded" if success else "failed"
        async with self.sessions() as db, db.begin():
            await db.execute(
                text(
                    "UPDATE project_workbench.image_edit_attempts "
                    "SET status=:status, error_message=:error, completed_at=now() WHERE id=:id"
                ),
                {"id": attempt_id, "status": status, "error": error},
            )
            await db.execute(
                text(
                    "UPDATE project_workbench.image_edit_tasks "
                    "SET status=:status, updated_at=now() WHERE id=:id"
                ),
                {"id": task_id, "status": status},
            )

    async def add_version(self, task_id: UUID, version: Any) -> Any:
        async with self.sessions() as db, db.begin():
            owner = (
                await db.execute(
                    text(
                        "SELECT workspace_id, project_id FROM project_workbench.image_edit_tasks "
                        "WHERE id=:id"
                    ),
                    {"id": task_id},
                )
            ).mappings().first()
            if owner is None:
                raise AppError("IMAGE_EDIT_TASK_NOT_FOUND", "图片编辑任务不存在", 404)
            await db.execute(
                text(
                    "INSERT INTO project_workbench.image_edit_versions "
                    "(id, workspace_id, project_id, task_id, attempt_id, version_number, "
                    "object_key, preview_url, source_snapshot, prompt_snapshot, config_snapshot, "
                    "is_current, is_final) "
                    "VALUES (:id, :workspace_id, :project_id, :task_id, :attempt_id, "
                    ":version_number, :object_key, :preview_url, CAST(:source AS jsonb), "
                    "CAST(:prompt AS jsonb), CAST(:config AS jsonb), TRUE, :is_final)"
                ),
                {
                    "id": version.id,
                    "workspace_id": owner["workspace_id"],
                    "project_id": owner["project_id"],
                    "task_id": task_id,
                    "attempt_id": version.attempt_id,
                    "version_number": version.version_number,
                    "object_key": version.object_key,
                    "preview_url": version.preview_url,
                    "source": _dump(version.source_snapshot),
                    "prompt": _dump(version.prompt_snapshot),
                    "config": _dump(version.config_snapshot),
                    "is_final": bool(version.is_final),
                },
            )
            await db.execute(
                text(
                    "UPDATE project_workbench.image_edit_tasks "
                    "SET current_version_id=:version_id, updated_at=now() WHERE id=:id"
                ),
                {"id": task_id, "version_id": version.id},
            )
        version.is_current = True
        return version

    async def retry_attempt(self, attempt_id: UUID, workspace_id: UUID) -> ImageEditTaskRecord | None:
        async with self.sessions() as db, db.begin():
            found = (
                await db.execute(
                    text(
                        "SELECT t.id, t.workspace_id, t.project_id "
                        "FROM project_workbench.image_edit_attempts a "
                        "JOIN project_workbench.image_edit_tasks t ON t.id = a.task_id "
                        "WHERE a.id=:id AND a.status='failed' AND t.workspace_id=:workspace_id "
                        "FOR UPDATE OF t"
                    ),
                    {"id": attempt_id, "workspace_id": workspace_id},
                )
            ).mappings().first()
            if found is None:
                return None
            next_number = await db.scalar(
                text(
                    "SELECT COALESCE(MAX(attempt_number), 0) + 1 "
                    "FROM project_workbench.image_edit_attempts WHERE task_id=:id"
                ),
                {"id": found["id"]},
            )
            await db.execute(
                text(
                    "INSERT INTO project_workbench.image_edit_attempts "
                    "(id, workspace_id, project_id, task_id, attempt_number) "
                    "VALUES (:id, :workspace_id, :project_id, :task_id, :number)"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": found["workspace_id"],
                    "project_id": found["project_id"],
                    "task_id": found["id"],
                    "number": next_number,
                },
            )
            await db.execute(
                text(
                    "UPDATE project_workbench.image_edit_tasks "
                    "SET status='queued', updated_at=now() WHERE id=:id"
                ),
                {"id": found["id"]},
            )
            return await self._load_task(db, found["id"])

    async def select_version(
        self, task_id: UUID, version_id: UUID, workspace_id: UUID, selection: str
    ) -> Any:
        async with self.sessions() as db, db.begin():
            locked = (
                await db.execute(
                    text(
                        f"SELECT {_TASK_COLUMNS} FROM project_workbench.image_edit_tasks "
                        "WHERE id=:id AND workspace_id=:workspace_id FOR UPDATE"
                    ),
                    {"id": task_id, "workspace_id": workspace_id},
                )
            ).mappings().first()
            if locked is None:
                return None
            task = await self._load_task(db, task_id)
            target = next((item for item in task.versions if item.id == version_id), None)
            if target is None or not target.is_current:
                raise ValueError("incomplete")
            if selection == "final":
                await db.execute(
                    text(
                        "UPDATE project_workbench.image_edit_versions "
                        "SET is_final = (id = :version_id) WHERE task_id=:task_id"
                    ),
                    {"version_id": version_id, "task_id": task_id},
                )
                await db.execute(
                    text(
                        "UPDATE project_workbench.image_edit_tasks "
                        "SET final_version_id=:version_id, updated_at=now() WHERE id=:id"
                    ),
                    {"id": task_id, "version_id": version_id},
                )
                target.is_final = True
            else:
                await db.execute(
                    text(
                        "UPDATE project_workbench.image_edit_versions "
                        "SET is_current = (id = :version_id) WHERE task_id=:task_id"
                    ),
                    {"version_id": version_id, "task_id": task_id},
                )
                await db.execute(
                    text(
                        "UPDATE project_workbench.image_edit_tasks "
                        "SET current_version_id=:version_id, updated_at=now() WHERE id=:id"
                    ),
                    {"id": task_id, "version_id": version_id},
                )
                target.is_current = True
            return target

    async def archive_session(
        self, session_id: UUID, workspace_id: UUID
    ) -> ImageEditSessionRecord | None:
        async with self.sessions() as db, db.begin():
            row = await db.execute(
                text(
                    "UPDATE project_workbench.image_edit_sessions "
                    "SET status='archived', archived_at=now(), updated_at=now() "
                    "WHERE id=:id AND workspace_id=:workspace_id "
                    f"RETURNING {_SESSION_COLUMNS}"
                ),
                {"id": session_id, "workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _session_from_row(result) if result is not None else None

    async def ready(self) -> bool:
        try:
            async with self.sessions() as db:
                return bool(
                    await db.scalar(
                        text(
                            "SELECT to_regclass('project_workbench.image_edit_tasks') IS NOT NULL"
                        )
                    )
                )
        except Exception:
            return False

    @staticmethod
    async def _task_by_submit_key(
        db: AsyncSession, session_id: UUID, idempotency_key: str | None
    ) -> ImageEditTaskRecord:
        row = await db.execute(
            text(
                f"SELECT {_TASK_COLUMNS} FROM project_workbench.image_edit_tasks "
                "WHERE session_id=:session_id AND submit_idempotency_key=:key"
            ),
            {"session_id": session_id, "key": idempotency_key},
        )
        result = row.mappings().one()
        return await PostgresImageEditingRepository._load_task(db, result["id"])

    @staticmethod
    async def _load_task(db: AsyncSession, task_id: UUID) -> ImageEditTaskRecord:
        row = await db.execute(
            text(
                f"SELECT {_TASK_COLUMNS} FROM project_workbench.image_edit_tasks WHERE id=:id"
            ),
            {"id": task_id},
        )
        task = _task_from_row(row.mappings().one())
        attempts = await db.execute(
            text(
                f"SELECT {_ATTEMPT_COLUMNS} FROM project_workbench.image_edit_attempts "
                "WHERE task_id=:id ORDER BY attempt_number"
            ),
            {"id": task_id},
        )
        task.attempts = [_attempt_from_row(item) for item in attempts.mappings()]
        versions = await db.execute(
            text(
                f"SELECT {_VERSION_COLUMNS} FROM project_workbench.image_edit_versions "
                "WHERE task_id=:id ORDER BY version_number"
            ),
            {"id": task_id},
        )
        task.versions = [_version_from_row(item) for item in versions.mappings()]
        return task


_SESSION_COLUMNS = (
    "id, workspace_id, project_id, source_version_id, source_snapshot, "
    "operations_snapshot, revision, status, archived_at, created_at, updated_at"
)

_TASK_COLUMNS = (
    "id, workspace_id, project_id, session_id, revision, status, operations_snapshot, "
    "source_snapshot, prompt_snapshot, config_snapshot, current_version_id, "
    "final_version_id, created_at"
)

_ATTEMPT_COLUMNS = "id, task_id, attempt_number, status, error_message"

_VERSION_COLUMNS = (
    "id, task_id, attempt_id, version_number, object_key, preview_url, "
    "source_snapshot, prompt_snapshot, config_snapshot, is_current, is_final, created_at"
)

_OCR_COLUMNS = (
    "id, workspace_id, project_id, session_id, source_version_id, "
    "request_fingerprint, text, regions, provider_snapshot, created_at"
)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


async def _lock_session(
    db: AsyncSession, session_id: UUID, workspace_id: UUID
) -> ImageEditSessionRecord | None:
    row = await db.execute(
        text(
            f"SELECT {_SESSION_COLUMNS} FROM project_workbench.image_edit_sessions "
            "WHERE id=:id AND workspace_id=:workspace_id FOR UPDATE"
        ),
        {"id": session_id, "workspace_id": workspace_id},
    )
    result = row.mappings().first()
    return _session_from_row(result) if result is not None else None


async def _write_operations(
    db: AsyncSession, current: ImageEditSessionRecord, operations: list[dict[str, Any]]
) -> ImageEditSessionRecord:
    row = await db.execute(
        text(
            "UPDATE project_workbench.image_edit_sessions "
            "SET operations_snapshot=CAST(:operations AS jsonb), revision=revision+1, "
            "updated_at=now() WHERE id=:id "
            f"RETURNING {_SESSION_COLUMNS}"
        ),
        {"id": current.id, "operations": _dump(operations)},
    )
    record = _session_from_row(row.mappings().one())
    await _mirror_operations(db, current.id, operations)
    return record


async def _mirror_operations(
    db: AsyncSession, session_id: UUID, operations: list[dict[str, Any]]
) -> None:
    """把草稿同步到规范化的 image_edit_operations 表，保持两张表内容一致。"""
    await db.execute(
        text("DELETE FROM project_workbench.image_edit_operations WHERE session_id=:id"),
        {"id": session_id},
    )
    if not operations:
        return
    await db.execute(
        text(
            "INSERT INTO project_workbench.image_edit_operations "
            "(id, session_id, ordinal, operation_type, payload) "
            "VALUES (:id, :session_id, :ordinal, :operation_type, CAST(:payload AS jsonb))"
        ),
        [
            {
                "id": uuid4(),
                "session_id": session_id,
                "ordinal": index,
                "operation_type": str(item.get("type") or "unknown")[:40],
                "payload": _dump(item),
            }
            for index, item in enumerate(operations, start=1)
        ],
    )


def _session_from_row(row: Any) -> ImageEditSessionRecord:
    return ImageEditSessionRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        source_version_id=row["source_version_id"],
        source_snapshot=deepcopy(row["source_snapshot"] or {}),
        operations_snapshot=deepcopy(row["operations_snapshot"] or []),
        revision=row["revision"],
        status=row["status"],
        archived_at=row["archived_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _task_from_row(row: Any) -> ImageEditTaskRecord:
    return ImageEditTaskRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        session_id=row["session_id"],
        revision=row["revision"],
        status=row["status"],
        operations_snapshot=deepcopy(row["operations_snapshot"] or []),
        source_snapshot=deepcopy(row["source_snapshot"] or {}),
        prompt_snapshot=deepcopy(row["prompt_snapshot"] or {}),
        config_snapshot=deepcopy(row["config_snapshot"] or {}),
        current_version_id=row["current_version_id"],
        final_version_id=row["final_version_id"],
        created_at=row["created_at"],
    )


def _attempt_from_row(row: Any) -> ImageEditAttemptRecord:
    return ImageEditAttemptRecord(
        id=row["id"],
        task_id=row["task_id"],
        attempt_number=row["attempt_number"],
        status=row["status"],
        error_message=row["error_message"],
    )


def _version_from_row(row: Any) -> ImageEditVersionRecord:
    return ImageEditVersionRecord(
        id=row["id"],
        task_id=row["task_id"],
        attempt_id=row["attempt_id"],
        version_number=row["version_number"],
        object_key=row["object_key"],
        preview_url=row["preview_url"],
        source_snapshot=deepcopy(row["source_snapshot"] or {}),
        prompt_snapshot=deepcopy(row["prompt_snapshot"] or {}),
        config_snapshot=deepcopy(row["config_snapshot"] or {}),
        is_current=row["is_current"],
        is_final=row["is_final"],
        created_at=row["created_at"],
    )


def _ocr_from_row(row: Any) -> Any:
    # 局部导入：ImageOcrResultRecord 定义在应用服务里，模块级导入会形成循环。
    from .application.image_editing_service import ImageOcrResultRecord

    return ImageOcrResultRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        session_id=row["session_id"],
        source_version_id=row["source_version_id"],
        request_fingerprint=row["request_fingerprint"],
        text=row["text"],
        regions=deepcopy(row["regions"] or []),
        provider_snapshot=deepcopy(row["provider_snapshot"] or {}),
        created_at=row["created_at"],
    )
