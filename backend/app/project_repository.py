from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .core.errors import AppError


@dataclass
class ProjectRecord:
    id: UUID
    workspace_id: UUID
    name: str
    status: str = "active"
    archived_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ProjectSummaryRecord:
    project: ProjectRecord
    asset_count: int
    cover_asset_id: UUID | None


@dataclass
class AssetObjectRecord:
    id: UUID
    workspace_id: UUID
    storage_key: str
    original_filename: str
    media_type: str
    byte_size: int
    width: int
    height: int
    sha256: str
    state: str = "available"
    cleanup_attempted_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_OBJECT_FIELDS = (
    "id", "workspace_id", "storage_key", "original_filename", "media_type",
    "byte_size", "width", "height", "sha256", "state", "cleanup_attempted_at", "created_at",
)
_JOINED_OBJECT_COLUMNS = ", ".join(f"obj.{name} AS stored_{name}" for name in _OBJECT_FIELDS)


@dataclass
class ProjectAssetRecord:
    id: UUID
    project_id: UUID
    object_id: UUID
    kind: str
    source_asset_id: UUID | None = None
    generation_snapshot_id: UUID | None = None
    state: str = "available"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_kind: str = "upload"
    source_library_id: str | None = None
    source_resource_id: str | None = None
    source_resource_version_id: str | None = None
    source_snapshot: dict[str, Any] = field(default_factory=dict)


class InMemoryProjectRepository:
    """测试和本地无数据库场景使用的项目资产仓储。"""

    def __init__(self, backing_store: dict[str, Any] | None = None) -> None:
        self._state = backing_store if backing_store is not None else {}
        self._projects: dict[UUID, ProjectRecord] = self._state.setdefault("projects", {})
        self._objects: dict[UUID, AssetObjectRecord] = self._state.setdefault("objects", {})
        self._assets: dict[UUID, ProjectAssetRecord] = self._state.setdefault("assets", {})
        self._selections: dict[tuple[UUID, str], UUID] = self._state.setdefault("selections", {})

    async def create_project(self, name: str, workspace_id: UUID) -> ProjectRecord:
        now = datetime.now(timezone.utc)
        record = ProjectRecord(uuid4(), workspace_id, name, created_at=now, updated_at=now)
        self._projects[record.id] = record
        return record

    async def get_project(self, project_id: UUID, workspace_id: UUID) -> ProjectRecord | None:
        record = self._projects.get(project_id)
        return record if record is not None and record.workspace_id == workspace_id else None

    async def list_projects(
        self, workspace_id: UUID, *, include_archived: bool = False
    ) -> list[ProjectRecord]:
        records = [item for item in self._projects.values() if item.workspace_id == workspace_id]
        if not include_archived:
            records = [item for item in records if item.status == "active"]
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    async def list_project_summaries(
        self, workspace_id: UUID, *, include_archived: bool = False
    ) -> list[ProjectSummaryRecord]:
        projects = await self.list_projects(workspace_id, include_archived=include_archived)
        grouped: dict[UUID, list[ProjectAssetRecord]] = {project.id: [] for project in projects}
        for asset in self._assets.values():
            if asset.project_id in grouped and asset.state != "deleted":
                grouped[asset.project_id].append(asset)
        summaries = []
        for project in projects:
            assets = grouped[project.id]
            covers = [
                asset for asset in assets
                if asset.state == "available"
                and asset.kind in {"generated", "white_background"}
                and (obj := self._objects.get(asset.object_id)) is not None
                and obj.workspace_id == workspace_id and obj.state == "available"
            ]
            cover = max(covers, key=lambda a: (a.kind == "generated", a.created_at, a.id), default=None)
            summaries.append(ProjectSummaryRecord(project, len(assets), cover.id if cover else None))
        return summaries

    async def archive_project(self, project_id: UUID, workspace_id: UUID) -> ProjectRecord | None:
        record = await self.get_project(project_id, workspace_id)
        if record is None:
            return None
        now = datetime.now(timezone.utc)
        record.status = "archived"
        record.archived_at = now
        record.updated_at = now
        return record

    async def delete_project(self, project_id: UUID, workspace_id: UUID) -> bool:
        project = await self.get_project(project_id, workspace_id)
        if project is None:
            return False
        asset_ids = [asset.id for asset in self._assets.values() if asset.project_id == project_id]
        for asset_id in asset_ids:
            self._assets.pop(asset_id, None)
        for key in list(self._selections):
            if key[0] == project_id:
                del self._selections[key]
        del self._projects[project_id]
        return True

    async def create_object(
        self,
        workspace_id: UUID,
        storage_key: str,
        original_filename: str,
        media_type: str,
        byte_size: int,
        width: int,
        height: int,
        sha256: str,
        *,
        object_id: UUID | None = None,
    ) -> AssetObjectRecord:
        record = AssetObjectRecord(
            object_id or uuid4(), workspace_id, storage_key, original_filename, media_type, byte_size, width, height, sha256
        )
        self._objects[record.id] = record
        return record

    async def get_object(self, object_id: UUID, workspace_id: UUID) -> AssetObjectRecord | None:
        record = self._objects.get(object_id)
        return record if record is not None and record.workspace_id == workspace_id else None

    async def create_asset(
        self,
        project_id: UUID,
        object_id: UUID,
        kind: str,
        *,
        source_asset_id: UUID | None = None,
        generation_snapshot_id: UUID | None = None,
        source_kind: str = "upload",
        source_library_id: str | None = None,
        source_resource_id: str | None = None,
        source_resource_version_id: str | None = None,
        source_snapshot: dict[str, Any] | None = None,
    ) -> ProjectAssetRecord:
        project = self._projects.get(project_id)
        object_record = self._objects.get(object_id)
        if project is None or object_record is None or project.workspace_id != object_record.workspace_id:
            raise AppError("INVALID_PROJECT_ASSET", "project asset relationship is invalid", 400)
        if source_asset_id is not None:
            source = self._assets.get(source_asset_id)
            if source is None or source.project_id != project_id:
                raise AppError("INVALID_SOURCE_ASSET", "source asset does not belong to project", 400)
        record = ProjectAssetRecord(
            uuid4(), project_id, object_id, kind, source_asset_id, generation_snapshot_id,
            source_kind=source_kind, source_library_id=source_library_id,
            source_resource_id=source_resource_id, source_resource_version_id=source_resource_version_id,
            source_snapshot=source_snapshot or {},
        )
        self._assets[record.id] = record
        project.updated_at = datetime.now(timezone.utc)
        return record

    async def get_asset(self, asset_id: UUID, workspace_id: UUID) -> ProjectAssetRecord | None:
        asset = self._assets.get(asset_id)
        project = self._projects.get(asset.project_id) if asset is not None else None
        if project is None or project.workspace_id != workspace_id:
            return None
        return asset

    async def list_assets(self, project_id: UUID, workspace_id: UUID) -> list[ProjectAssetRecord]:
        project = await self.get_project(project_id, workspace_id)
        if project is None:
            return []
        return sorted(
            [
                asset
                for asset in self._assets.values()
                if asset.project_id == project_id and asset.state != "deleted"
            ],
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def object_reference_count(self, object_id: UUID) -> int:
        return sum(
            asset.object_id == object_id and asset.state != "deleted"
            for asset in self._assets.values()
        )

    async def list_asset_details(
        self, project_id: UUID, workspace_id: UUID
    ) -> list[tuple[ProjectAssetRecord, AssetObjectRecord | None]]:
        assets = await self.list_assets(project_id, workspace_id)
        return [(asset, obj if obj is not None and obj.workspace_id == workspace_id else None)
                for asset in assets for obj in [self._objects.get(asset.object_id)]]

    async def set_object_state(
        self, object_id: UUID, workspace_id: UUID, state: str
    ) -> AssetObjectRecord | None:
        record = await self.get_object(object_id, workspace_id)
        if record is None:
            return None
        record.state = state
        record.cleanup_attempted_at = datetime.now(timezone.utc)
        return record

    async def delete_asset(self, asset_id: UUID, workspace_id: UUID) -> ProjectAssetRecord | None:
        asset = await self.get_asset(asset_id, workspace_id)
        if asset is None:
            return None
        if any(
            other.source_asset_id == asset.id and other.state != "deleted"
            for other in self._assets.values()
        ):
            raise AppError("ASSET_IN_USE", "asset is still referenced by a derived asset", 409)
        asset.state = "deleted"
        for key, selected_id in list(self._selections.items()):
            if selected_id == asset.id:
                del self._selections[key]
        return asset

    async def select_asset(
        self, project_id: UUID, role: str, asset_id: UUID, workspace_id: UUID
    ) -> ProjectAssetRecord | None:
        asset = await self.get_asset(asset_id, workspace_id)
        if asset is None or asset.project_id != project_id or asset.kind != role:
            return None
        self._selections[(project_id, role)] = asset_id
        return asset

    async def clear_selection(self, project_id: UUID, role: str, workspace_id: UUID) -> bool:
        if await self.get_project(project_id, workspace_id) is None:
            return False
        return self._selections.pop((project_id, role), None) is not None

    async def get_selections(self, project_id: UUID, workspace_id: UUID) -> dict[str, UUID]:
        if await self.get_project(project_id, workspace_id) is None:
            return {}
        return {role: asset_id for (selected_project, role), asset_id in self._selections.items() if selected_project == project_id}

    async def ready(self) -> bool:
        return True


class PostgresProjectRepository:
    """以 PostgreSQL 持久化项目资产域的仓储适配器。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create_project(self, name: str, workspace_id: UUID) -> ProjectRecord:
        project_id = uuid4()
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.projects(id, workspace_id, name) "
                    "VALUES (:id, :workspace_id, :name) "
                    "RETURNING id, workspace_id, name, status, archived_at, created_at, updated_at"
                ),
                {"id": project_id, "workspace_id": workspace_id, "name": name},
            )
            return _project_record(row.mappings().one())

    async def get_project(self, project_id: UUID, workspace_id: UUID) -> ProjectRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT id, workspace_id, name, status, archived_at, created_at, updated_at "
                    "FROM project_workbench.projects WHERE id=:id AND workspace_id=:workspace_id"
                ),
                {"id": project_id, "workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _project_record(result) if result is not None else None

    async def list_projects(
        self, workspace_id: UUID, *, include_archived: bool = False
    ) -> list[ProjectRecord]:
        status_filter = "" if include_archived else " AND status='active'"
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    "SELECT id, workspace_id, name, status, archived_at, created_at, updated_at "
                    "FROM project_workbench.projects WHERE workspace_id=:workspace_id"
                    f"{status_filter} ORDER BY updated_at DESC"
                ),
                {"workspace_id": workspace_id},
            )
            return [_project_record(row) for row in rows.mappings()]

    async def list_project_summaries(
        self, workspace_id: UUID, *, include_archived: bool = False
    ) -> list[ProjectSummaryRecord]:
        status_filter = "" if include_archived else " AND project.status='active'"
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    "SELECT project.*, summary.asset_count, summary.cover_asset_id "
                    "FROM project_workbench.projects project "
                    "LEFT JOIN LATERAL ("
                    "SELECT count(*) AS asset_count, "
                    "(array_agg(asset.id ORDER BY (asset.kind='generated') DESC, asset.created_at DESC, asset.id DESC) "
                    "FILTER (WHERE asset.kind IN ('generated', 'white_background') "
                    "AND asset.state='available' AND obj.state='available'))[1] AS cover_asset_id "
                    "FROM project_workbench.project_assets asset "
                    "LEFT JOIN project_workbench.asset_objects obj ON obj.id=asset.object_id "
                    "AND obj.workspace_id=:workspace_id "
                    "WHERE asset.project_id=project.id AND asset.state <> 'deleted'"
                    ") summary ON true "
                    f"WHERE project.workspace_id=:workspace_id{status_filter} ORDER BY project.updated_at DESC"
                ),
                {"workspace_id": workspace_id},
            )
            return [ProjectSummaryRecord(_project_record(row), row["asset_count"], row["cover_asset_id"])
                    for row in rows.mappings()]

    async def archive_project(self, project_id: UUID, workspace_id: UUID) -> ProjectRecord | None:
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.projects SET status='archived', archived_at=now(), "
                    "updated_at=now() WHERE id=:id AND workspace_id=:workspace_id "
                    "RETURNING id, workspace_id, name, status, archived_at, created_at, updated_at"
                ),
                {"id": project_id, "workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _project_record(result) if result is not None else None

    async def delete_project(self, project_id: UUID, workspace_id: UUID) -> bool:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "DELETE FROM project_workbench.projects WHERE id=:id AND workspace_id=:workspace_id "
                    "RETURNING id"
                ),
                {"id": project_id, "workspace_id": workspace_id},
            )
            return result.first() is not None

    async def create_object(
        self,
        workspace_id: UUID,
        storage_key: str,
        original_filename: str,
        media_type: str,
        byte_size: int,
        width: int,
        height: int,
        sha256: str,
        *,
        object_id: UUID | None = None,
    ) -> AssetObjectRecord:
        resolved_object_id = object_id or uuid4()
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.asset_objects("
                    "id, workspace_id, storage_key, original_filename, media_type, byte_size, width, height, sha256) "
                    "VALUES (:id, :workspace_id, :storage_key, :original_filename, :media_type, :byte_size, :width, :height, :sha256) "
                    "RETURNING id, workspace_id, storage_key, original_filename, media_type, byte_size, width, height, sha256, state, "
                    "cleanup_attempted_at, created_at"
                ),
                {
                    "id": resolved_object_id,
                    "workspace_id": workspace_id,
                    "storage_key": storage_key,
                    "original_filename": original_filename,
                    "media_type": media_type,
                    "byte_size": byte_size,
                    "width": width,
                    "height": height,
                    "sha256": sha256,
                },
            )
            return _object_record(row.mappings().one())

    async def get_object(self, object_id: UUID, workspace_id: UUID) -> AssetObjectRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT id, workspace_id, storage_key, original_filename, media_type, byte_size, width, height, sha256, state, "
                    "cleanup_attempted_at, created_at FROM project_workbench.asset_objects "
                    "WHERE id=:id AND workspace_id=:workspace_id"
                ),
                {"id": object_id, "workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _object_record(result) if result is not None else None

    async def create_asset(
        self,
        project_id: UUID,
        object_id: UUID,
        kind: str,
        *,
        source_asset_id: UUID | None = None,
        generation_snapshot_id: UUID | None = None,
        source_kind: str = "upload",
        source_library_id: str | None = None,
        source_resource_id: str | None = None,
        source_resource_version_id: str | None = None,
        source_snapshot: dict[str, Any] | None = None,
    ) -> ProjectAssetRecord:
        asset_id = uuid4()
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.project_assets("
                    "id, project_id, object_id, kind, source_asset_id, generation_snapshot_id, source_kind, "
                    "source_library_id, source_resource_id, source_resource_version_id, source_snapshot) "
                    "SELECT :id, project.id, object.id, :kind, :source_asset_id, :generation_snapshot_id, :source_kind, "
                    ":source_library_id, :source_resource_id, :source_resource_version_id, CAST(:source_snapshot AS jsonb) "
                    "FROM project_workbench.projects project "
                    "JOIN project_workbench.asset_objects object "
                    "ON object.id=:object_id AND object.workspace_id=project.workspace_id "
                    "WHERE project.id=:project_id "
                    "RETURNING id, project_id, object_id, kind, source_asset_id, generation_snapshot_id, state, created_at, source_kind, source_library_id, source_resource_id, source_resource_version_id, source_snapshot"
                ),
                {
                    "id": asset_id,
                    "project_id": project_id,
                    "object_id": object_id,
                    "kind": kind,
                    "source_asset_id": source_asset_id,
                    "generation_snapshot_id": generation_snapshot_id,
                    "source_kind": source_kind,
                    "source_library_id": source_library_id,
                    "source_resource_id": source_resource_id,
                    "source_resource_version_id": source_resource_version_id,
                    "source_snapshot": json.dumps(source_snapshot or {}),
                },
            )
            result = row.mappings().first()
            if result is None:
                raise AppError("INVALID_PROJECT_ASSET", "project asset relationship is invalid", 400)
            return _asset_record(result)

    async def get_asset(self, asset_id: UUID, workspace_id: UUID) -> ProjectAssetRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT asset.id, asset.project_id, asset.object_id, asset.kind, asset.source_asset_id, "
                    "asset.generation_snapshot_id, asset.state, asset.created_at, asset.source_kind, asset.source_library_id, "
                    "asset.source_resource_id, asset.source_resource_version_id, asset.source_snapshot "
                    "FROM project_workbench.project_assets asset "
                    "JOIN project_workbench.projects project ON project.id=asset.project_id "
                    "WHERE asset.id=:id AND project.workspace_id=:workspace_id"
                ),
                {"id": asset_id, "workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _asset_record(result) if result is not None else None

    async def list_assets(self, project_id: UUID, workspace_id: UUID) -> list[ProjectAssetRecord]:
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    "SELECT asset.id, asset.project_id, asset.object_id, asset.kind, asset.source_asset_id, "
                    "asset.generation_snapshot_id, asset.state, asset.created_at, asset.source_kind, asset.source_library_id, "
                    "asset.source_resource_id, asset.source_resource_version_id, asset.source_snapshot "
                    "FROM project_workbench.project_assets asset "
                    "JOIN project_workbench.projects project ON project.id=asset.project_id "
                    "WHERE asset.project_id=:project_id AND project.workspace_id=:workspace_id "
                    "AND asset.state <> 'deleted' ORDER BY asset.created_at DESC"
                ),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
            return [_asset_record(row) for row in rows.mappings()]

    async def object_reference_count(self, object_id: UUID) -> int:
        async with self.sessions() as session:
            return int(
                await session.scalar(
                    text(
                        "SELECT count(*) FROM project_workbench.project_assets "
                        "WHERE object_id=:object_id AND state <> 'deleted'"
                    ),
                    {"object_id": object_id},
                )
                or 0
            )

    async def list_asset_details(
        self, project_id: UUID, workspace_id: UUID
    ) -> list[tuple[ProjectAssetRecord, AssetObjectRecord | None]]:
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    f"SELECT asset.*, {_JOINED_OBJECT_COLUMNS} "
                    "FROM project_workbench.project_assets asset "
                    "JOIN project_workbench.projects project ON project.id=asset.project_id "
                    "LEFT JOIN project_workbench.asset_objects obj ON obj.id=asset.object_id "
                    "AND obj.workspace_id=:workspace_id "
                    "WHERE asset.project_id=:project_id AND project.workspace_id=:workspace_id "
                    "AND asset.state <> 'deleted' ORDER BY asset.created_at DESC"
                ),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
            return [
                (_asset_record(row), _object_record({name: row[f"stored_{name}"] for name in _OBJECT_FIELDS})
                 if row["stored_id"] is not None else None)
                for row in rows.mappings()
            ]

    async def set_object_state(
        self, object_id: UUID, workspace_id: UUID, state: str
    ) -> AssetObjectRecord | None:
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.asset_objects SET state=:state, cleanup_attempted_at=now() "
                    "WHERE id=:id AND workspace_id=:workspace_id "
                    "RETURNING id, workspace_id, storage_key, original_filename, media_type, byte_size, "
                    "width, height, sha256, state, cleanup_attempted_at, created_at"
                ),
                {"id": object_id, "workspace_id": workspace_id, "state": state},
            )
            result = row.mappings().first()
            return _object_record(result) if result is not None else None

    async def delete_asset(self, asset_id: UUID, workspace_id: UUID) -> ProjectAssetRecord | None:
        async with self.sessions() as session, session.begin():
            existing = await self.get_asset(asset_id, workspace_id)
            if existing is None:
                return None
            referenced = await session.scalar(
                text(
                    "SELECT count(*) FROM project_workbench.project_assets "
                    "WHERE source_asset_id=:asset_id AND state <> 'deleted'"
                ),
                {"asset_id": asset_id},
            )
            if referenced:
                raise AppError("ASSET_IN_USE", "asset is still referenced by a derived asset", 409)
            row = await session.execute(
                text(
                    "UPDATE project_workbench.project_assets SET state='deleted' WHERE id=:id "
                    "RETURNING id, project_id, object_id, kind, source_asset_id, generation_snapshot_id, state, created_at, source_kind, source_library_id, source_resource_id, source_resource_version_id, source_snapshot"
                ),
                {"id": asset_id},
            )
            await session.execute(
                text(
                    "DELETE FROM project_workbench.project_asset_selections WHERE project_asset_id=:asset_id"
                ),
                {"asset_id": asset_id},
            )
            return _asset_record(row.mappings().one())

    async def select_asset(
        self, project_id: UUID, role: str, asset_id: UUID, workspace_id: UUID
    ) -> ProjectAssetRecord | None:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "INSERT INTO project_workbench.project_asset_selections("
                    "project_id, role, project_asset_id) "
                    "SELECT project.id, :role, asset.id FROM project_workbench.projects project "
                    "JOIN project_workbench.project_assets asset "
                    "ON asset.id=:asset_id AND asset.project_id=project.id AND asset.kind=:role "
                    "WHERE project.id=:project_id AND project.workspace_id=:workspace_id "
                    "ON CONFLICT (project_id, role) DO UPDATE SET "
                    "project_asset_id=EXCLUDED.project_asset_id, updated_at=now() RETURNING project_asset_id"
                ),
                {"project_id": project_id, "role": role, "asset_id": asset_id, "workspace_id": workspace_id},
            )
            row = result.first()
            return await self.get_asset(row[0], workspace_id) if row is not None else None

    async def clear_selection(self, project_id: UUID, role: str, workspace_id: UUID) -> bool:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "DELETE FROM project_workbench.project_asset_selections selection "
                    "USING project_workbench.projects project "
                    "WHERE selection.project_id=project.id AND selection.project_id=:project_id "
                    "AND selection.role=:role AND project.workspace_id=:workspace_id RETURNING selection.project_id"
                ),
                {"project_id": project_id, "role": role, "workspace_id": workspace_id},
            )
            return result.first() is not None

    async def get_selections(self, project_id: UUID, workspace_id: UUID) -> dict[str, UUID]:
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    "SELECT selection.role, selection.project_asset_id "
                    "FROM project_workbench.project_asset_selections selection "
                    "JOIN project_workbench.projects project ON project.id=selection.project_id "
                    "WHERE selection.project_id=:project_id AND project.workspace_id=:workspace_id"
                ),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
            return {row["role"]: row["project_asset_id"] for row in rows.mappings()}

    async def ready(self) -> bool:
        try:
            async with self.sessions() as session:
                return bool(
                    await session.scalar(
                        text("SELECT to_regclass('project_workbench.projects') IS NOT NULL")
                    )
                )
        except Exception:
            return False


def _project_record(row: Any) -> ProjectRecord:
    return ProjectRecord(
        row["id"], row["workspace_id"], row["name"], row["status"], row["archived_at"],
        row["created_at"], row["updated_at"],
    )


def _object_record(row: Any) -> AssetObjectRecord:
    return AssetObjectRecord(
        row["id"], row["workspace_id"], row["storage_key"], row["original_filename"],
        row["media_type"], row["byte_size"], row["width"], row["height"], row["sha256"],
        row["state"], row["cleanup_attempted_at"], row["created_at"],
    )


def _asset_record(row: Any) -> ProjectAssetRecord:
    return ProjectAssetRecord(
        row["id"], row["project_id"], row["object_id"], row["kind"], row["source_asset_id"],
        row["generation_snapshot_id"], row["state"], row["created_at"], row.get("source_kind", "upload"),
        row.get("source_library_id"), row.get("source_resource_id"), row.get("source_resource_version_id"), row.get("source_snapshot") or {},
    )
