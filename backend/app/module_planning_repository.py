"""Durable outline jobs, scoped by workspace/project and idempotency key."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from uuid import uuid4

from sqlalchemy import text

from .core.errors import AppError


def _check(row, fingerprint):
    if row["fingerprint"] != fingerprint:
        raise AppError("IDEMPOTENCY_KEY_REUSED", "幂等键已用于其他规划", 409)


def _expired(value):
    return value["status"] == "planning" and datetime.fromisoformat(value["createdAt"]) < datetime.now(timezone.utc) - timedelta(minutes=10)


def _timeout(value):
    value.update(status="failed", error={"code": "MODULE_PLANNER_INTERRUPTED", "message": "规划已超时或中断，请重新规划"})
    return value


class MemoryModulePlanningRepository:
    def __init__(self):
        self.records = {}

    async def create(self, workspace, project, key, fingerprint, value):
        for row in self.records.values():
            if (row["workspace"], row["project"], row["key"]) == (workspace, project, key):
                _check(row, fingerprint)
                return await self.get(workspace, project, row["id"]), False
        plan_id = uuid4()
        value = {**deepcopy(value), "id": str(plan_id), "createdAt": datetime.now(timezone.utc).isoformat()}
        self.records[plan_id] = dict(id=plan_id, workspace=workspace, project=project, key=key, fingerprint=fingerprint, value=value)
        return deepcopy(value), True

    async def get(self, workspace, project, plan_id):
        row = self.records.get(plan_id)
        if not row or (row["workspace"], row["project"]) != (workspace, project):
            return None
        if _expired(row["value"]):
            _timeout(row["value"])
        return deepcopy(row["value"])

    async def latest(self, workspace, project, mode):
        rows = [r for r in self.records.values() if (r["workspace"], r["project"], r["value"]["mode"]) == (workspace, project, mode) and r["value"].get("origin") != "planning_conversation"]
        return await self.get(workspace, project, max(rows, key=lambda r: r["value"]["createdAt"])["id"]) if rows else None

    async def save(self, workspace, project, plan_id, value):
        row = self.records.get(plan_id)
        if not row or (row["workspace"], row["project"]) != (workspace, project):
            raise AppError("MODULE_PLAN_NOT_FOUND", "规划不存在", 404)
        if row["value"]["status"] == "planning":
            row["value"] = deepcopy(value)
        return deepcopy(row["value"])


class PostgresModulePlanningRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def create(self, workspace, project, key, fingerprint, value):
        plan_id = uuid4()
        value = {**deepcopy(value), "id": str(plan_id), "createdAt": datetime.now(timezone.utc).isoformat()}
        params = dict(id=plan_id, workspace=workspace, project=project, key=key, fingerprint=fingerprint,
                      mode=value["mode"], value=json.dumps(value, ensure_ascii=False))
        async with self.sessions() as session, session.begin():
            inserted = await session.execute(text(
                "INSERT INTO project_workbench.module_plans (id, workspace_id, project_id, request_key, fingerprint, mode, document) "
                "VALUES (:id, :workspace, :project, :key, :fingerprint, :mode, CAST(:value AS jsonb)) "
                "ON CONFLICT (workspace_id, project_id, request_key) DO NOTHING RETURNING id"), params)
            if inserted.scalar_one_or_none():
                return value, True
            row = (await session.execute(text(
                "SELECT fingerprint, document FROM project_workbench.module_plans "
                "WHERE workspace_id=:workspace AND project_id=:project AND request_key=:key"), params)).mappings().one()
            _check(row, fingerprint)
            saved = _document(row["document"])
        from uuid import UUID
        return await self.get(workspace, project, UUID(saved["id"])), False

    async def get(self, workspace, project, plan_id):
        async with self.sessions() as session, session.begin():
            raw = await session.scalar(text(
                "SELECT document FROM project_workbench.module_plans WHERE id=:id AND workspace_id=:workspace AND project_id=:project FOR UPDATE"),
                dict(id=plan_id, workspace=workspace, project=project))
            if raw is None:
                return None
            value = _document(raw)
            if _expired(value):
                _timeout(value)
                await session.execute(text("UPDATE project_workbench.module_plans SET document=CAST(:value AS jsonb) WHERE id=:id"),
                                      dict(id=plan_id, value=json.dumps(value, ensure_ascii=False)))
            return value

    async def latest(self, workspace, project, mode):
        async with self.sessions() as session:
            plan_id = await session.scalar(text(
                "SELECT id FROM project_workbench.module_plans WHERE workspace_id=:workspace AND project_id=:project AND mode=:mode "
                "AND COALESCE(document->>'origin','') != 'planning_conversation' ORDER BY created_at DESC, id DESC LIMIT 1"), dict(workspace=workspace, project=project, mode=mode))
        return await self.get(workspace, project, plan_id) if plan_id else None

    async def save(self, workspace, project, plan_id, value):
        async with self.sessions() as session, session.begin():
            await session.execute(text(
                "UPDATE project_workbench.module_plans SET document=CAST(:value AS jsonb) "
                "WHERE id=:id AND workspace_id=:workspace AND project_id=:project AND document->>'status'='planning'"),
                dict(id=plan_id, workspace=workspace, project=project, value=json.dumps(value, ensure_ascii=False)))
        return await self.get(workspace, project, plan_id)


def _document(value):
    return json.loads(value) if isinstance(value, str) else deepcopy(value)
