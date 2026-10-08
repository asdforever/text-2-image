import asyncio
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


def empty_overall() -> dict[str, str]:
    return {
        "contentFlow": "",
        "visualSystem": "",
        "moduleStrategy": "",
        "adaptationRules": "",
    }


@dataclass
class ReverseReferenceRecord:
    id: UUID
    workspace_id: UUID
    reverse_project_id: UUID
    ordinal: int
    filename: str
    width: int
    height: int
    mime_type: str
    storage_key: str
    sha256: str
    created_at: datetime = field(default_factory=_now)


@dataclass
class ReverseVersionRecord:
    id: UUID
    workspace_id: UUID
    reverse_project_id: UUID
    version_no: int
    revision: int
    document: dict[str, Any]
    created_at: datetime = field(default_factory=_now)


@dataclass
class ReverseBindingRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    project_name: str
    target: str
    scope: str
    target_module_id: str | None
    reverse_project_id: UUID
    reverse_project_name: str
    version_id: UUID
    version_no: int
    source_module_id: str | None
    source_module_title: str | None
    created_at: datetime = field(default_factory=_now)


@dataclass
class ReverseProjectRecord:
    id: UUID
    workspace_id: UUID
    name: str
    category: str = ""
    summary: str = ""
    suitable_for: str = ""
    goal: str = ""
    required_materials: str = ""
    not_suitable_for: str = ""
    overall: dict[str, str] = field(default_factory=empty_overall)
    modules: list[dict[str, str]] = field(default_factory=list)
    analysis_status: str = "idle"
    analysis_error: str | None = None
    revision: int = 1
    references: list[ReverseReferenceRecord] = field(default_factory=list)
    versions: list[ReverseVersionRecord] = field(default_factory=list)
    latest_version_id: UUID | None = None
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    analysis_token: UUID | None = None


def copy_project(record: ReverseProjectRecord) -> ReverseProjectRecord:
    return deepcopy(record)


def _not_found() -> AppError:
    return AppError("REVERSE_PROJECT_NOT_FOUND", "反推项目不存在", 404)


def _conflict() -> AppError:
    return AppError("REVERSE_PROJECT_REVISION_CONFLICT", "反推草稿已被更新，请重新加载", 409)


class InMemoryReverseProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[UUID, ReverseProjectRecord] = {}
        self.references: dict[UUID, ReverseReferenceRecord] = {}
        self.version_records: dict[UUID, ReverseVersionRecord] = {}
        self.bindings: dict[UUID, ReverseBindingRecord] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}

    def _lock(self, project_id: UUID) -> asyncio.Lock:
        return self._locks.setdefault(project_id, asyncio.Lock())

    def _project(self, workspace_id: UUID, project_id: UUID) -> ReverseProjectRecord:
        record = self.projects.get(project_id)
        if record is None or record.workspace_id != workspace_id:
            raise _not_found()
        return record

    async def create_project(
        self, workspace_id: UUID, name: str, category: str
    ) -> ReverseProjectRecord:
        record = ReverseProjectRecord(uuid4(), workspace_id, name, category)
        self.projects[record.id] = record
        return copy_project(record)

    async def list_projects(self, workspace_id: UUID) -> list[ReverseProjectRecord]:
        return [
            copy_project(item)
            for item in sorted(
                self.projects.values(), key=lambda value: value.updated_at, reverse=True
            )
            if item.workspace_id == workspace_id
        ]

    async def get_project(
        self, workspace_id: UUID, project_id: UUID
    ) -> ReverseProjectRecord | None:
        record = self.projects.get(project_id)
        return copy_project(record) if record and record.workspace_id == workspace_id else None

    async def update_project(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        changes: dict[str, Any],
    ) -> ReverseProjectRecord:
        async with self._lock(project_id):
            project = self._project(workspace_id, project_id)
            if project.revision != expected_revision:
                raise _conflict()
            for field_name, value in changes.items():
                setattr(project, field_name, deepcopy(value))
            project.revision += 1
            project.updated_at = _now()
            return copy_project(project)

    async def add_reference(
        self, workspace_id: UUID, project_id: UUID, reference: ReverseReferenceRecord
    ) -> ReverseProjectRecord:
        async with self._lock(project_id):
            project = self._project(workspace_id, project_id)
            project.references.append(reference)
            self.references[reference.id] = reference
            project.revision += 1
            project.updated_at = _now()
            return copy_project(project)

    async def remove_reference(
        self, workspace_id: UUID, project_id: UUID, reference_id: UUID
    ) -> ReverseProjectRecord:
        async with self._lock(project_id):
            project = self._project(workspace_id, project_id)
            if not any(item.id == reference_id for item in project.references):
                raise AppError("REVERSE_REFERENCE_NOT_FOUND", "参考图不存在", 404)
            project.references = [item for item in project.references if item.id != reference_id]
            for ordinal, item in enumerate(project.references, 1):
                item.ordinal = ordinal
            project.revision += 1
            project.updated_at = _now()
            return copy_project(project)

    async def reorder_references(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        reference_ids: list[UUID],
    ) -> ReverseProjectRecord:
        async with self._lock(project_id):
            project = self._project(workspace_id, project_id)
            if project.revision != expected_revision:
                raise _conflict()
            current = {item.id: item for item in project.references}
            if len(reference_ids) != len(current) or set(reference_ids) != set(current):
                raise AppError("REVERSE_REFERENCE_ORDER_INVALID", "参考图排序必须包含全部图片", 400)
            project.references = [current[item_id] for item_id in reference_ids]
            for ordinal, item in enumerate(project.references, 1):
                item.ordinal = ordinal
            project.revision += 1
            project.updated_at = _now()
            return copy_project(project)

    async def get_reference(
        self, workspace_id: UUID, project_id: UUID, reference_id: UUID
    ) -> ReverseReferenceRecord | None:
        item = self.references.get(reference_id)
        if item is None or item.workspace_id != workspace_id or item.reverse_project_id != project_id:
            return None
        return deepcopy(item)

    async def claim_analysis(
        self, workspace_id: UUID, project_id: UUID, expected_revision: int
    ) -> ReverseProjectRecord:
        async with self._lock(project_id):
            project = self._project(workspace_id, project_id)
            if project.revision != expected_revision:
                raise _conflict()
            if project.analysis_status == "running":
                raise AppError("REVERSE_ANALYSIS_RUNNING", "反推分析正在进行中", 409)
            project.analysis_status = "running"
            project.analysis_error = None
            project.analysis_token = uuid4()
            return copy_project(project)

    async def complete_analysis(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        result: dict[str, Any],
    ) -> ReverseProjectRecord:
        async with self._lock(project_id):
            project = self._project(workspace_id, project_id)
            if project.revision != expected_revision:
                raise _conflict()
            for field_name, value in result.items():
                setattr(project, field_name, deepcopy(value))
            project.analysis_status = "completed"
            project.analysis_error = None
            project.analysis_token = None
            project.revision += 1
            project.updated_at = _now()
            return copy_project(project)

    async def fail_analysis(
        self, workspace_id: UUID, project_id: UUID, message: str,
        *, expected_analysis_token: UUID | None = None,
    ) -> ReverseProjectRecord:
        async with self._lock(project_id):
            project = self._project(workspace_id, project_id)
            if expected_analysis_token is not None and (
                project.analysis_token != expected_analysis_token or project.analysis_status != "running"
            ):
                return copy_project(project)
            project.analysis_status = "failed"
            project.analysis_error = message
            project.analysis_token = None
            return copy_project(project)

    async def publish(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        document: dict[str, Any],
    ) -> ReverseVersionRecord:
        async with self._lock(project_id):
            project = self._project(workspace_id, project_id)
            existing = next(
                (item for item in project.versions if item.revision == expected_revision), None
            )
            if existing is not None:
                return deepcopy(existing)
            if project.revision != expected_revision:
                raise _conflict()
            version = ReverseVersionRecord(
                uuid4(), workspace_id, project_id, len(project.versions) + 1,
                project.revision, deepcopy(document)
            )
            project.versions.append(version)
            project.latest_version_id = version.id
            project.updated_at = _now()
            self.version_records[version.id] = version
            return deepcopy(version)

    async def get_version(
        self, workspace_id: UUID, version_id: UUID
    ) -> ReverseVersionRecord | None:
        record = self.version_records.get(version_id)
        return deepcopy(record) if record and record.workspace_id == workspace_id else None

    async def put_binding(
        self,
        workspace_id: UUID,
        project_id: UUID,
        project_name: str,
        target: str,
        scope: str,
        target_module_id: str | None,
        version: ReverseVersionRecord,
        reverse_project_name: str,
        source_module_id: str | None,
        source_module_title: str | None,
    ) -> ReverseBindingRecord:
        for binding_id, item in list(self.bindings.items()):
            if (
                item.workspace_id == workspace_id
                and item.project_id == project_id
                and item.target == target
                and item.scope == scope
                and item.target_module_id == target_module_id
            ):
                del self.bindings[binding_id]
        record = ReverseBindingRecord(
            uuid4(), workspace_id, project_id, project_name, target, scope,
            target_module_id, version.reverse_project_id, reverse_project_name,
            version.id, version.version_no, source_module_id, source_module_title,
        )
        self.bindings[record.id] = record
        return deepcopy(record)

    async def list_project_bindings(
        self, workspace_id: UUID, project_id: UUID, target: str | None = None
    ) -> list[ReverseBindingRecord]:
        return [
            deepcopy(item)
            for item in sorted(self.bindings.values(), key=lambda value: value.created_at)
            if item.workspace_id == workspace_id
            and item.project_id == project_id
            and (target is None or item.target == target)
        ]

    async def list_reverse_bindings(
        self, workspace_id: UUID, reverse_project_id: UUID
    ) -> list[ReverseBindingRecord]:
        self._project(workspace_id, reverse_project_id)
        return [
            deepcopy(item)
            for item in sorted(self.bindings.values(), key=lambda value: value.created_at)
            if item.workspace_id == workspace_id
            and item.reverse_project_id == reverse_project_id
        ]

    async def delete_binding(
        self, workspace_id: UUID, project_id: UUID, binding_id: UUID
    ) -> bool:
        record = self.bindings.get(binding_id)
        if record is None or record.workspace_id != workspace_id or record.project_id != project_id:
            return False
        del self.bindings[binding_id]
        return True


class PostgresReverseProjectRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create_project(
        self, workspace_id: UUID, name: str, category: str
    ) -> ReverseProjectRecord:
        project_id = uuid4()
        async with self.sessions() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO project_workbench.reverse_projects "
                    "(id,workspace_id,name,category,overall) VALUES "
                    "(:id,:workspace_id,:name,:category,CAST(:overall AS jsonb))"
                ),
                {
                    "id": project_id,
                    "workspace_id": workspace_id,
                    "name": name,
                    "category": category,
                    "overall": json.dumps(empty_overall()),
                },
            )
        project = await self.get_project(workspace_id, project_id)
        if project is None:
            raise RuntimeError("reverse project insert did not persist")
        return project

    async def list_projects(self, workspace_id: UUID) -> list[ReverseProjectRecord]:
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    "SELECT id FROM project_workbench.reverse_projects "
                    "WHERE workspace_id=:workspace_id ORDER BY updated_at DESC"
                ),
                {"workspace_id": workspace_id},
            )
            project_ids = [row[0] for row in rows]
        projects = [await self.get_project(workspace_id, project_id) for project_id in project_ids]
        return [project for project in projects if project is not None]

    async def get_project(
        self, workspace_id: UUID, project_id: UUID
    ) -> ReverseProjectRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT * FROM project_workbench.reverse_projects "
                    "WHERE id=:id AND workspace_id=:workspace_id"
                ),
                {"id": project_id, "workspace_id": workspace_id},
            )
            project_row = row.mappings().first()
            if project_row is None:
                return None
            references = await session.execute(
                text(
                    "SELECT * FROM project_workbench.reverse_project_references "
                    "WHERE reverse_project_id=:id AND workspace_id=:workspace_id AND active "
                    "ORDER BY ordinal"
                ),
                {"id": project_id, "workspace_id": workspace_id},
            )
            versions = await session.execute(
                text(
                    "SELECT * FROM project_workbench.reverse_versions "
                    "WHERE reverse_project_id=:id AND workspace_id=:workspace_id "
                    "ORDER BY version_no"
                ),
                {"id": project_id, "workspace_id": workspace_id},
            )
            return _postgres_project(
                project_row,
                [_postgres_reference(item) for item in references.mappings()],
                [_postgres_version(item) for item in versions.mappings()],
            )

    async def update_project(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        changes: dict[str, Any],
    ) -> ReverseProjectRecord:
        async with self.sessions() as session, session.begin():
            row = await self._locked_project(session, workspace_id, project_id)
            if row["revision"] != expected_revision:
                raise _conflict()
            values = {
                "name": row["name"],
                "category": row["category"],
                "summary": row["summary"],
                "suitable_for": row["suitable_for"],
                "goal": row["goal"],
                "required_materials": row["required_materials"],
                "not_suitable_for": row["not_suitable_for"],
                "overall": row["overall"],
                "modules": row["modules"],
            }
            values.update(deepcopy(changes))
            await session.execute(
                text(
                    "UPDATE project_workbench.reverse_projects SET "
                    "name=:name,category=:category,summary=:summary,suitable_for=:suitable_for,"
                    "goal=:goal,required_materials=:required_materials,not_suitable_for=:not_suitable_for,"
                    "overall=CAST(:overall AS jsonb),modules=CAST(:modules AS jsonb),"
                    "revision=revision+1,updated_at=now() WHERE id=:id"
                ),
                {
                    **values,
                    "overall": json.dumps(values["overall"], ensure_ascii=False),
                    "modules": json.dumps(values["modules"], ensure_ascii=False),
                    "id": project_id,
                },
            )
        return await self._required_project(workspace_id, project_id)

    async def add_reference(
        self, workspace_id: UUID, project_id: UUID, reference: ReverseReferenceRecord
    ) -> ReverseProjectRecord:
        async with self.sessions() as session, session.begin():
            await self._locked_project(session, workspace_id, project_id)
            await session.execute(
                text(
                    "INSERT INTO project_workbench.reverse_project_references "
                    "(id,workspace_id,reverse_project_id,ordinal,filename,width,height,mime_type,storage_key,sha256) "
                    "VALUES (:id,:workspace_id,:project_id,:ordinal,:filename,:width,:height,:mime_type,:storage_key,:sha256)"
                ),
                {
                    "id": reference.id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "ordinal": reference.ordinal,
                    "filename": reference.filename,
                    "width": reference.width,
                    "height": reference.height,
                    "mime_type": reference.mime_type,
                    "storage_key": reference.storage_key,
                    "sha256": reference.sha256,
                },
            )
            await self._bump_revision(session, project_id)
        return await self._required_project(workspace_id, project_id)

    async def remove_reference(
        self, workspace_id: UUID, project_id: UUID, reference_id: UUID
    ) -> ReverseProjectRecord:
        async with self.sessions() as session, session.begin():
            await self._locked_project(session, workspace_id, project_id)
            result = await session.execute(
                text(
                    "UPDATE project_workbench.reverse_project_references SET active=false "
                    "WHERE id=:id AND reverse_project_id=:project_id AND workspace_id=:workspace_id "
                    "AND active RETURNING id"
                ),
                {"id": reference_id, "project_id": project_id, "workspace_id": workspace_id},
            )
            if result.first() is None:
                raise AppError("REVERSE_REFERENCE_NOT_FOUND", "参考图不存在", 404)
            await self._compact_ordinals(session, project_id)
            await self._bump_revision(session, project_id)
        return await self._required_project(workspace_id, project_id)

    async def reorder_references(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        reference_ids: list[UUID],
    ) -> ReverseProjectRecord:
        async with self.sessions() as session, session.begin():
            project = await self._locked_project(session, workspace_id, project_id)
            if project["revision"] != expected_revision:
                raise _conflict()
            rows = await session.execute(
                text(
                    "SELECT id FROM project_workbench.reverse_project_references "
                    "WHERE reverse_project_id=:project_id AND active ORDER BY ordinal"
                ),
                {"project_id": project_id},
            )
            current = [row[0] for row in rows]
            if len(reference_ids) != len(current) or set(reference_ids) != set(current):
                raise AppError("REVERSE_REFERENCE_ORDER_INVALID", "参考图排序必须包含全部图片", 400)
            await session.execute(
                text(
                    "UPDATE project_workbench.reverse_project_references "
                    "SET ordinal=ordinal+1000 WHERE reverse_project_id=:project_id AND active"
                ),
                {"project_id": project_id},
            )
            for ordinal, reference_id in enumerate(reference_ids, 1):
                await session.execute(
                    text(
                        "UPDATE project_workbench.reverse_project_references SET ordinal=:ordinal "
                        "WHERE id=:id AND reverse_project_id=:project_id AND active"
                    ),
                    {"ordinal": ordinal, "id": reference_id, "project_id": project_id},
                )
            await self._bump_revision(session, project_id)
        return await self._required_project(workspace_id, project_id)

    async def get_reference(
        self, workspace_id: UUID, project_id: UUID, reference_id: UUID
    ) -> ReverseReferenceRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT * FROM project_workbench.reverse_project_references "
                    "WHERE id=:id AND workspace_id=:workspace_id AND reverse_project_id=:project_id"
                ),
                {"id": reference_id, "workspace_id": workspace_id, "project_id": project_id},
            )
            result = row.mappings().first()
            return _postgres_reference(result) if result else None

    async def claim_analysis(
        self, workspace_id: UUID, project_id: UUID, expected_revision: int
    ) -> ReverseProjectRecord:
        async with self.sessions() as session, session.begin():
            project = await self._locked_project(session, workspace_id, project_id)
            if project["revision"] != expected_revision:
                raise _conflict()
            if project["analysis_status"] == "running":
                raise AppError("REVERSE_ANALYSIS_RUNNING", "反推分析正在进行中", 409)
            await session.execute(
                text(
                    "UPDATE project_workbench.reverse_projects "
                    "SET analysis_status='running',analysis_error=NULL,analysis_token=:token WHERE id=:id"
                ),
                {"id": project_id, "token": uuid4()},
            )
        return await self._required_project(workspace_id, project_id)

    async def complete_analysis(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        result: dict[str, Any],
    ) -> ReverseProjectRecord:
        async with self.sessions() as session, session.begin():
            project = await self._locked_project(session, workspace_id, project_id)
            if project["revision"] != expected_revision:
                raise _conflict()
            await session.execute(
                text(
                    "UPDATE project_workbench.reverse_projects SET category=:category,summary=:summary,"
                    "suitable_for=:suitable_for,goal=:goal,required_materials=:required_materials,"
                    "not_suitable_for=:not_suitable_for,overall=CAST(:overall AS jsonb),"
                    "modules=CAST(:modules AS jsonb),analysis_status='completed',analysis_error=NULL,analysis_token=NULL,"
                    "revision=revision+1,updated_at=now() WHERE id=:id"
                ),
                {
                    **result,
                    "overall": json.dumps(result["overall"], ensure_ascii=False),
                    "modules": json.dumps(result["modules"], ensure_ascii=False),
                    "id": project_id,
                },
            )
        return await self._required_project(workspace_id, project_id)

    async def fail_analysis(
        self, workspace_id: UUID, project_id: UUID, message: str,
        *, expected_analysis_token: UUID | None = None,
    ) -> ReverseProjectRecord:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "UPDATE project_workbench.reverse_projects SET analysis_status='failed',"
                    "analysis_error=:message,analysis_token=NULL WHERE id=:id AND workspace_id=:workspace_id "
                    "AND (CAST(:analysis_token AS uuid) IS NULL "
                    "OR (analysis_token=:analysis_token AND analysis_status='running')) RETURNING id"
                ),
                {"message": message, "id": project_id, "workspace_id": workspace_id,
                 "analysis_token": expected_analysis_token},
            )
            if result.first() is None and expected_analysis_token is None:
                raise _not_found()
        return await self._required_project(workspace_id, project_id)

    async def publish(
        self,
        workspace_id: UUID,
        project_id: UUID,
        expected_revision: int,
        document: dict[str, Any],
    ) -> ReverseVersionRecord:
        async with self.sessions() as session, session.begin():
            project = await self._locked_project(session, workspace_id, project_id)
            existing = await session.execute(
                text(
                    "SELECT * FROM project_workbench.reverse_versions "
                    "WHERE reverse_project_id=:project_id AND revision=:revision"
                ),
                {"project_id": project_id, "revision": expected_revision},
            )
            existing_row = existing.mappings().first()
            if existing_row:
                return _postgres_version(existing_row)
            if project["revision"] != expected_revision:
                raise _conflict()
            version_no = int(
                await session.scalar(
                    text(
                        "SELECT COALESCE(MAX(version_no),0)+1 FROM project_workbench.reverse_versions "
                        "WHERE reverse_project_id=:project_id"
                    ),
                    {"project_id": project_id},
                )
            )
            version_id = uuid4()
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.reverse_versions "
                    "(id,workspace_id,reverse_project_id,version_no,revision,document) VALUES "
                    "(:id,:workspace_id,:project_id,:version_no,:revision,CAST(:document AS jsonb)) "
                    "RETURNING *"
                ),
                {
                    "id": version_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "version_no": version_no,
                    "revision": expected_revision,
                    "document": json.dumps(document, ensure_ascii=False),
                },
            )
            await session.execute(
                text(
                    "UPDATE project_workbench.reverse_projects "
                    "SET latest_version_id=:version_id,updated_at=now() WHERE id=:project_id"
                ),
                {"version_id": version_id, "project_id": project_id},
            )
            return _postgres_version(row.mappings().one())

    async def get_version(
        self, workspace_id: UUID, version_id: UUID
    ) -> ReverseVersionRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT * FROM project_workbench.reverse_versions "
                    "WHERE id=:id AND workspace_id=:workspace_id"
                ),
                {"id": version_id, "workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _postgres_version(result) if result else None

    async def put_binding(
        self,
        workspace_id: UUID,
        project_id: UUID,
        project_name: str,
        target: str,
        scope: str,
        target_module_id: str | None,
        version: ReverseVersionRecord,
        reverse_project_name: str,
        source_module_id: str | None,
        source_module_title: str | None,
    ) -> ReverseBindingRecord:
        binding_id = uuid4()
        async with self.sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:slot))"),
                {"slot": f"{workspace_id}:{project_id}:{target}:{scope}:{target_module_id or ''}"},
            )
            await session.execute(
                text(
                    "DELETE FROM project_workbench.reverse_bindings WHERE workspace_id=:workspace_id "
                    "AND project_id=:project_id AND target=:target AND scope=:scope "
                    "AND target_module_id IS NOT DISTINCT FROM :target_module_id"
                ),
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "target": target,
                    "scope": scope,
                    "target_module_id": target_module_id,
                },
            )
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.reverse_bindings "
                    "(id,workspace_id,project_id,reverse_project_id,version_id,target,scope,"
                    "target_module_id,source_module_id) VALUES "
                    "(:id,:workspace_id,:project_id,:reverse_project_id,:version_id,:target,:scope,"
                    ":target_module_id,:source_module_id) RETURNING created_at"
                ),
                {
                    "id": binding_id,
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "reverse_project_id": version.reverse_project_id,
                    "version_id": version.id,
                    "target": target,
                    "scope": scope,
                    "target_module_id": target_module_id,
                    "source_module_id": source_module_id,
                },
            )
            created_at = row.scalar_one()
        return ReverseBindingRecord(
            binding_id, workspace_id, project_id, project_name, target, scope,
            target_module_id, version.reverse_project_id, reverse_project_name,
            version.id, version.version_no, source_module_id, source_module_title, created_at,
        )

    async def list_project_bindings(
        self, workspace_id: UUID, project_id: UUID, target: str | None = None
    ) -> list[ReverseBindingRecord]:
        condition = " AND binding.target=:target" if target else ""
        params: dict[str, Any] = {"workspace_id": workspace_id, "project_id": project_id}
        if target:
            params["target"] = target
        async with self.sessions() as session:
            rows = await session.execute(
                text(self._binding_query("binding.project_id=:project_id" + condition)), params
            )
            return [_postgres_binding(row) for row in rows.mappings()]

    async def list_reverse_bindings(
        self, workspace_id: UUID, reverse_project_id: UUID
    ) -> list[ReverseBindingRecord]:
        async with self.sessions() as session:
            exists = await session.scalar(
                text(
                    "SELECT 1 FROM project_workbench.reverse_projects "
                    "WHERE id=:id AND workspace_id=:workspace_id"
                ),
                {"id": reverse_project_id, "workspace_id": workspace_id},
            )
            if not exists:
                raise _not_found()
            rows = await session.execute(
                text(self._binding_query("binding.reverse_project_id=:reverse_project_id")),
                {"workspace_id": workspace_id, "reverse_project_id": reverse_project_id},
            )
            return [_postgres_binding(row) for row in rows.mappings()]

    async def delete_binding(
        self, workspace_id: UUID, project_id: UUID, binding_id: UUID
    ) -> bool:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "DELETE FROM project_workbench.reverse_bindings "
                    "WHERE id=:id AND workspace_id=:workspace_id AND project_id=:project_id RETURNING id"
                ),
                {"id": binding_id, "workspace_id": workspace_id, "project_id": project_id},
            )
            return result.first() is not None

    async def _locked_project(
        self, session: AsyncSession, workspace_id: UUID, project_id: UUID
    ) -> Any:
        row = await session.execute(
            text(
                "SELECT * FROM project_workbench.reverse_projects "
                "WHERE id=:id AND workspace_id=:workspace_id FOR UPDATE"
            ),
            {"id": project_id, "workspace_id": workspace_id},
        )
        result = row.mappings().first()
        if result is None:
            raise _not_found()
        return result

    async def _required_project(
        self, workspace_id: UUID, project_id: UUID
    ) -> ReverseProjectRecord:
        project = await self.get_project(workspace_id, project_id)
        if project is None:
            raise _not_found()
        return project

    @staticmethod
    async def _bump_revision(session: AsyncSession, project_id: UUID) -> None:
        await session.execute(
            text(
                "UPDATE project_workbench.reverse_projects "
                "SET revision=revision+1,updated_at=now() WHERE id=:id"
            ),
            {"id": project_id},
        )

    @staticmethod
    async def _compact_ordinals(session: AsyncSession, project_id: UUID) -> None:
        rows = await session.execute(
            text(
                "SELECT id FROM project_workbench.reverse_project_references "
                "WHERE reverse_project_id=:project_id AND active ORDER BY ordinal"
            ),
            {"project_id": project_id},
        )
        ids = [row[0] for row in rows]
        await session.execute(
            text(
                "UPDATE project_workbench.reverse_project_references SET ordinal=ordinal+1000 "
                "WHERE reverse_project_id=:project_id AND active"
            ),
            {"project_id": project_id},
        )
        for ordinal, reference_id in enumerate(ids, 1):
            await session.execute(
                text(
                    "UPDATE project_workbench.reverse_project_references SET ordinal=:ordinal "
                    "WHERE id=:id"
                ),
                {"ordinal": ordinal, "id": reference_id},
            )

    @staticmethod
    def _binding_query(condition: str) -> str:
        return (
            "SELECT binding.*, project.name AS project_name, reverse.name AS reverse_project_name, "
            "version.version_no, module.value->>'title' AS source_module_title "
            "FROM project_workbench.reverse_bindings binding "
            "JOIN project_workbench.projects project ON project.id=binding.project_id "
            "JOIN project_workbench.reverse_projects reverse ON reverse.id=binding.reverse_project_id "
            "JOIN project_workbench.reverse_versions version ON version.id=binding.version_id "
            "LEFT JOIN LATERAL jsonb_array_elements(version.document->'modules') module(value) "
            "ON module.value->>'id'=binding.source_module_id "
            f"WHERE binding.workspace_id=:workspace_id AND {condition} ORDER BY binding.created_at"
        )


def _postgres_reference(row: Any) -> ReverseReferenceRecord:
    return ReverseReferenceRecord(
        row["id"], row["workspace_id"], row["reverse_project_id"], row["ordinal"],
        row["filename"], row["width"], row["height"], row["mime_type"],
        row["storage_key"], row["sha256"], row["created_at"],
    )


def _postgres_version(row: Any) -> ReverseVersionRecord:
    return ReverseVersionRecord(
        row["id"], row["workspace_id"], row["reverse_project_id"], row["version_no"],
        row["revision"], deepcopy(row["document"]), row["created_at"],
    )


def _postgres_project(
    row: Any,
    references: list[ReverseReferenceRecord],
    versions: list[ReverseVersionRecord],
) -> ReverseProjectRecord:
    return ReverseProjectRecord(
        id=row["id"], workspace_id=row["workspace_id"], name=row["name"],
        category=row["category"], summary=row["summary"], suitable_for=row["suitable_for"],
        goal=row["goal"], required_materials=row["required_materials"],
        not_suitable_for=row["not_suitable_for"], overall=deepcopy(row["overall"]),
        modules=deepcopy(row["modules"]), analysis_status=row["analysis_status"],
        analysis_token=row.get("analysis_token"),
        analysis_error=row["analysis_error"], revision=row["revision"], references=references,
        versions=versions, latest_version_id=row["latest_version_id"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _postgres_binding(row: Any) -> ReverseBindingRecord:
    return ReverseBindingRecord(
        row["id"], row["workspace_id"], row["project_id"], row["project_name"],
        row["target"], row["scope"], row["target_module_id"], row["reverse_project_id"],
        row["reverse_project_name"], row["version_id"], row["version_no"],
        row["source_module_id"], row["source_module_title"], row["created_at"],
    )
