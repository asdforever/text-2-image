"""Durable generation snapshots and attempts, independent of editable plans."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from .core.errors import AppError


def _now():
    return datetime.now(timezone.utc)


def _busy():
    return AppError("REVERSE_BATCH_RUNNING", "此方案已有生成中的批次，请等待完成", 409)


def _missing():
    return AppError("REVERSE_BATCH_NOT_FOUND", "反推批次不存在", 404)


@dataclass
class ReverseBatchRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    plan_id: UUID
    batch_no: int
    document: dict[str, Any]
    revision: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


class MemoryReverseBatchRepository:
    def __init__(self):
        self.records: dict[UUID, ReverseBatchRecord] = {}

    async def list(self, workspace_id, project_id, plan_id=None):
        return deepcopy(sorted((r for r in self.records.values() if r.workspace_id == workspace_id
            and r.project_id == project_id and (plan_id is None or r.plan_id == plan_id)),
            key=lambda r: (r.created_at, str(r.id)), reverse=True))

    async def get(self, workspace_id, project_id, batch_id, plan_id=None):
        return next((r for r in await self.list(workspace_id, project_id, plan_id) if r.id == batch_id), None)

    async def create(self, workspace_id, project_id, plan_id, document):
        existing = await self.list(workspace_id, project_id, plan_id)
        if any(r.document.get("status") == "running" for r in existing):
            raise _busy()
        record = ReverseBatchRecord(uuid4(), workspace_id, project_id, plan_id,
            max((r.batch_no for r in existing), default=0) + 1, deepcopy(document))
        self.records[record.id] = record
        return deepcopy(record)

    async def save(self, record, document):
        current = self.records.get(record.id)
        if current is None:
            raise _missing()
        if current.revision != record.revision:
            raise AppError("REVERSE_BATCH_REVISION_CONFLICT", "批次已被更新，请重新加载", 409)
        current.document = deepcopy(document)
        current.revision += 1
        current.updated_at = _now()
        return deepcopy(current)

    async def claim(self, record, deadline):
        existing = await self.list(record.workspace_id, record.project_id, record.plan_id)
        if any(r.document.get("status") == "running" for r in existing):
            raise _busy()
        return await self.save(record, {**record.document, "status": "running", "leaseExpiresAt": deadline})

    async def ready(self):
        return True


class PostgresReverseBatchRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def list(self, workspace_id, project_id, plan_id=None):
        async with self.sessions() as session:
            rows = await session.execute(text(
                "SELECT * FROM project_workbench.reverse_execution_batches "
                "WHERE workspace_id=:workspace AND project_id=:project "
                + ("AND plan_id=:plan " if plan_id is not None else "")
                + "ORDER BY created_at DESC,id DESC"),
                {"workspace": workspace_id, "project": project_id, "plan": plan_id})
            return [_record(row) for row in rows.mappings()]

    async def get(self, workspace_id, project_id, batch_id, plan_id=None):
        async with self.sessions() as session:
            rows = await session.execute(text(
                "SELECT * FROM project_workbench.reverse_execution_batches "
                "WHERE workspace_id=:workspace AND project_id=:project AND id=:batch "
                + ("AND plan_id=:plan" if plan_id is not None else "")),
                {"workspace": workspace_id, "project": project_id, "batch": batch_id, "plan": plan_id})
            row = rows.mappings().first()
            return _record(row) if row else None

    async def _lock_plan(self, session, workspace, project, plan):
        row = await session.scalar(text(
            "SELECT id FROM project_workbench.reverse_execution_plans "
            "WHERE workspace_id=:workspace AND project_id=:project AND id=:plan FOR UPDATE"),
            {"workspace": workspace, "project": project, "plan": plan})
        if row is None:
            raise AppError("REVERSE_EXECUTION_NOT_FOUND", "反推方案不存在", 404)
        running = await session.scalar(text(
            "SELECT id FROM project_workbench.reverse_execution_batches "
            "WHERE plan_id=:plan AND document->>'status'='running' LIMIT 1"), {"plan": plan})
        if running:
            raise _busy()

    async def create(self, workspace_id, project_id, plan_id, document):
        async with self.sessions() as session, session.begin():
            await self._lock_plan(session, workspace_id, project_id, plan_id)
            number = await session.scalar(text(
                "SELECT COALESCE(MAX(batch_no),0)+1 FROM project_workbench.reverse_execution_batches WHERE plan_id=:plan"),
                {"plan": plan_id})
            result = await session.execute(text(
                "INSERT INTO project_workbench.reverse_execution_batches (id,workspace_id,project_id,plan_id,batch_no,document) "
                "VALUES (:id,:workspace,:project,:plan,:number,CAST(:document AS jsonb)) RETURNING *"),
                {"id": uuid4(), "workspace": workspace_id, "project": project_id, "plan": plan_id,
                 "number": number, "document": json.dumps(document, ensure_ascii=False)})
            return _record(result.mappings().one())

    async def _save(self, session, record, document):
        result = await session.execute(text(
            "UPDATE project_workbench.reverse_execution_batches SET document=CAST(:document AS jsonb), "
            "revision=revision+1,updated_at=now() WHERE id=:id AND workspace_id=:workspace "
            "AND project_id=:project AND plan_id=:plan AND revision=:revision RETURNING *"),
            {"id": record.id, "workspace": record.workspace_id, "project": record.project_id,
             "plan": record.plan_id, "revision": record.revision, "document": json.dumps(document, ensure_ascii=False)})
        row = result.mappings().first()
        if row is None:
            raise AppError("REVERSE_BATCH_REVISION_CONFLICT", "批次已被更新，请重新加载", 409)
        return _record(row)

    async def save(self, record, document):
        async with self.sessions() as session, session.begin():
            return await self._save(session, record, document)

    async def claim(self, record, deadline):
        async with self.sessions() as session, session.begin():
            await self._lock_plan(session, record.workspace_id, record.project_id, record.plan_id)
            return await self._save(session, record, {**record.document, "status": "running", "leaseExpiresAt": deadline})

    async def ready(self):
        async with self.sessions() as session:
            return bool(await session.scalar(text("SELECT to_regclass('project_workbench.reverse_execution_batches') IS NOT NULL")))


def _record(row):
    document = json.loads(row["document"]) if isinstance(row["document"], str) else row["document"]
    return ReverseBatchRecord(row["id"], row["workspace_id"], row["project_id"], row["plan_id"],
        row["batch_no"], deepcopy(document), row["revision"], row["created_at"], row["updated_at"])
