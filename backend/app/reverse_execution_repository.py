"""Persistence for project-level reverse execution plans."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from .core.errors import AppError


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conflict() -> AppError:
    return AppError("REVERSE_EXECUTION_REVISION_CONFLICT", "项目反推方案已被更新，请重新加载", 409)


@dataclass
class ReverseExecutionPlanRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    reverse_version_id: UUID
    document: dict[str, Any]
    revision: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


class InMemoryReverseExecutionRepository:
    def __init__(self) -> None:
        self.records: dict[UUID, ReverseExecutionPlanRecord] = {}

    async def list(self, workspace_id: UUID, project_id: UUID) -> list[ReverseExecutionPlanRecord]:
        return deepcopy(sorted((record for record in self.records.values()
            if record.workspace_id == workspace_id and record.project_id == project_id),
            key=lambda record: (record.created_at, str(record.id)), reverse=True))

    async def get(self, workspace_id: UUID, project_id: UUID, plan_id: UUID | None = None) -> ReverseExecutionPlanRecord | None:
        records = await self.list(workspace_id, project_id)
        return next((record for record in records if plan_id is None or record.id == plan_id), None)

    async def create(
        self, workspace_id: UUID, project_id: UUID, reverse_version_id: UUID, document: dict[str, Any]
    ) -> ReverseExecutionPlanRecord:
        record = ReverseExecutionPlanRecord(
            uuid4(), workspace_id, project_id, reverse_version_id, deepcopy(document)
        )
        self.records[record.id] = record
        return deepcopy(record)

    async def save(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        document: dict[str, Any],
        plan_id: UUID | None = None,
    ) -> ReverseExecutionPlanRecord:
        record = await self.get(workspace_id, project_id, plan_id)
        if record is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        if record.revision != expected_revision:
            raise _conflict()
        record.document = deepcopy(document)
        record.revision += 1
        record.updated_at = _now()
        self.records[record.id] = record
        return deepcopy(record)

    async def ready(self) -> bool:
        return True


class PostgresReverseExecutionRepository:
    def __init__(self, sessions) -> None:
        self.sessions = sessions

    async def list(self, workspace_id: UUID, project_id: UUID) -> list[ReverseExecutionPlanRecord]:
        async with self.sessions() as session:
            rows = await session.execute(text(
                "SELECT id, workspace_id, project_id, reverse_version_id, document, revision, created_at, updated_at "
                "FROM project_workbench.reverse_execution_plans WHERE workspace_id=:workspace AND project_id=:project "
                "ORDER BY created_at DESC,id DESC"), {"workspace": workspace_id, "project": project_id})
            return [_record(row) for row in rows.mappings()]

    async def get(self, workspace_id: UUID, project_id: UUID, plan_id: UUID | None = None) -> ReverseExecutionPlanRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT id, workspace_id, project_id, reverse_version_id, document, revision, created_at, updated_at "
                    "FROM project_workbench.reverse_execution_plans "
                    "WHERE workspace_id=:workspace AND project_id=:project "
                    + ("AND id=:plan " if plan_id is not None else "")
                    + "ORDER BY created_at DESC,id DESC LIMIT 1"
                ),
                {"workspace": workspace_id, "project": project_id, "plan": plan_id},
            )
            value = row.mappings().first()
            return _record(value) if value else None

    async def create(
        self, workspace_id: UUID, project_id: UUID, reverse_version_id: UUID, document: dict[str, Any]
    ) -> ReverseExecutionPlanRecord:
        record = ReverseExecutionPlanRecord(
            uuid4(), workspace_id, project_id, reverse_version_id, deepcopy(document)
        )
        async with self.sessions() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO project_workbench.reverse_execution_plans "
                    "(id,workspace_id,project_id,reverse_version_id,document,revision) "
                    "VALUES (:id,:workspace,:project,:version,CAST(:document AS jsonb),:revision)"
                ),
                {
                    "id": record.id,
                    "workspace": workspace_id,
                    "project": project_id,
                    "version": reverse_version_id,
                    "document": json.dumps(document, ensure_ascii=False),
                    "revision": 1,
                },
            )
        saved = await self.get(workspace_id, project_id, record.id)
        if saved is None:
            raise RuntimeError("reverse execution plan insert did not persist")
        return saved

    async def save(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        document: dict[str, Any],
        plan_id: UUID | None = None,
    ) -> ReverseExecutionPlanRecord:
        current = await self.get(workspace_id, project_id, plan_id)
        if current is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE project_workbench.reverse_execution_plans SET document=CAST(:document AS jsonb), "
                    "revision=revision+1, updated_at=now() "
                    "WHERE workspace_id=:workspace AND project_id=:project AND id=:plan AND revision=:revision "
                    "RETURNING id"
                ),
                {
                    "workspace": workspace_id,
                    "project": project_id,
                    "revision": expected_revision,
                    "plan": current.id,
                    "document": json.dumps(document, ensure_ascii=False),
                },
            )
            if result.first() is None:
                existing = await self.get(workspace_id, project_id, current.id)
                if existing is None:
                    raise AppError("REVERSE_EXECUTION_NOT_FOUND", "项目反推方案不存在", 404)
                raise _conflict()
        saved = await self.get(workspace_id, project_id, current.id)
        if saved is None:
            raise RuntimeError("reverse execution plan update did not persist")
        return saved

    async def ready(self) -> bool:
        try:
            async with self.sessions() as session:
                return bool(await session.scalar(text("SELECT to_regclass('project_workbench.reverse_execution_plans') IS NOT NULL")))
        except Exception:
            return False


def _record(row: Any) -> ReverseExecutionPlanRecord:
    document = row["document"]
    if isinstance(document, str):
        document = json.loads(document)
    return ReverseExecutionPlanRecord(
        row["id"], row["workspace_id"], row["project_id"], row["reverse_version_id"],
        deepcopy(document), row["revision"], row["created_at"], row["updated_at"],
    )
