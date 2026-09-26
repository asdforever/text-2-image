import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .core.errors import AppError


def generation_config_hash(content: dict[str, Any]) -> str:
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConfigVersionRecord:
    id: UUID
    workspace_id: UUID
    version_no: int
    content: dict[str, Any]
    content_sha256: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ConfigDraftRecord:
    workspace_id: UUID
    base_version_no: int
    content: dict[str, Any]
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GenerationConfigRepository(Protocol):
    async def bootstrap(
        self, workspace_id: UUID, default_content: dict[str, Any]
    ) -> tuple[ConfigVersionRecord, ConfigDraftRecord]: ...

    async def get_current(self, workspace_id: UUID) -> ConfigVersionRecord | None: ...

    async def get_version(
        self, workspace_id: UUID, version_no: int
    ) -> ConfigVersionRecord | None: ...

    async def list_versions(self, workspace_id: UUID) -> list[ConfigVersionRecord]: ...

    async def publish(self, workspace_id: UUID, content: dict[str, Any]) -> ConfigVersionRecord: ...

    async def get_draft(self, workspace_id: UUID) -> ConfigDraftRecord | None: ...

    async def replace_draft(
        self, workspace_id: UUID, base_version_no: int, content: dict[str, Any]
    ) -> ConfigDraftRecord: ...

    async def discard_draft(self, workspace_id: UUID) -> bool: ...

    async def replace_draft_if_current(
        self, workspace_id: UUID, base_version_no: int, content: dict[str, Any]
    ) -> ConfigDraftRecord: ...

    async def reset_draft(self, workspace_id: UUID) -> ConfigDraftRecord: ...

    async def publish_draft(
        self,
        workspace_id: UUID,
        expected_base_version_no: int,
        expected_draft: dict[str, Any],
        content: dict[str, Any],
        saved_at: str,
    ) -> ConfigVersionRecord: ...


class InMemoryGenerationConfigRepository:
    """用于测试和无数据库运行时的生成配置仓储。"""

    def __init__(self, backing_store: dict[str, Any] | None = None) -> None:
        self._state = backing_store if backing_store is not None else {}
        self._versions: dict[UUID, list[ConfigVersionRecord]] = self._state.setdefault(
            "generation_config_versions", {}
        )
        self._drafts: dict[UUID, ConfigDraftRecord] = self._state.setdefault(
            "generation_config_drafts", {}
        )
        self._locks: dict[UUID, asyncio.Lock] = self._state.setdefault(
            "generation_config_locks", {}
        )

    def _lock(self, workspace_id: UUID) -> asyncio.Lock:
        return self._locks.setdefault(workspace_id, asyncio.Lock())

    async def bootstrap(
        self, workspace_id: UUID, default_content: dict[str, Any]
    ) -> tuple[ConfigVersionRecord, ConfigDraftRecord]:
        async with self._lock(workspace_id):
            versions = self._versions.setdefault(workspace_id, [])
            if not versions:
                initial = deepcopy(default_content)
                initial["version"] = 1
                record = ConfigVersionRecord(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    version_no=1,
                    content=initial,
                    content_sha256=generation_config_hash(initial),
                )
                versions.append(record)
            current = versions[-1]
            draft = self._drafts.get(workspace_id)
            if draft is None:
                draft = ConfigDraftRecord(
                    workspace_id, current.version_no, deepcopy(current.content)
                )
                self._drafts[workspace_id] = draft
            return _copy_version(current), _copy_draft(draft)

    async def get_current(self, workspace_id: UUID) -> ConfigVersionRecord | None:
        versions = self._versions.get(workspace_id, [])
        return _copy_version(versions[-1]) if versions else None

    async def get_version(
        self, workspace_id: UUID, version_no: int
    ) -> ConfigVersionRecord | None:
        version = next(
            (item for item in self._versions.get(workspace_id, []) if item.version_no == version_no),
            None,
        )
        return _copy_version(version) if version else None

    async def list_versions(self, workspace_id: UUID) -> list[ConfigVersionRecord]:
        return [_copy_version(item) for item in self._versions.get(workspace_id, [])]

    async def publish(self, workspace_id: UUID, content: dict[str, Any]) -> ConfigVersionRecord:
        versions = self._versions.setdefault(workspace_id, [])
        record = ConfigVersionRecord(
            id=uuid4(),
            workspace_id=workspace_id,
            version_no=len(versions) + 1,
            content=deepcopy(content),
            content_sha256=generation_config_hash(content),
        )
        versions.append(record)
        return _copy_version(record)

    async def get_draft(self, workspace_id: UUID) -> ConfigDraftRecord | None:
        draft = self._drafts.get(workspace_id)
        return _copy_draft(draft) if draft else None

    async def replace_draft(
        self, workspace_id: UUID, base_version_no: int, content: dict[str, Any]
    ) -> ConfigDraftRecord:
        record = ConfigDraftRecord(workspace_id, base_version_no, deepcopy(content))
        self._drafts[workspace_id] = record
        return _copy_draft(record)

    async def replace_draft_if_current(
        self, workspace_id: UUID, base_version_no: int, content: dict[str, Any]
    ) -> ConfigDraftRecord:
        async with self._lock(workspace_id):
            current = self._versions.get(workspace_id, [])
            if not current or current[-1].version_no != base_version_no:
                _draft_conflict()
            record = ConfigDraftRecord(workspace_id, base_version_no, deepcopy(content))
            self._drafts[workspace_id] = record
            return _copy_draft(record)

    async def discard_draft(self, workspace_id: UUID) -> bool:
        return self._drafts.pop(workspace_id, None) is not None

    async def reset_draft(self, workspace_id: UUID) -> ConfigDraftRecord:
        async with self._lock(workspace_id):
            current = self._versions.get(workspace_id, [])
            if not current:
                raise RuntimeError("generation config must be initialized before reset")
            record = ConfigDraftRecord(
                workspace_id, current[-1].version_no, deepcopy(current[-1].content)
            )
            self._drafts[workspace_id] = record
            return _copy_draft(record)

    async def publish_draft(
        self,
        workspace_id: UUID,
        expected_base_version_no: int,
        expected_draft: dict[str, Any],
        content: dict[str, Any],
        saved_at: str,
    ) -> ConfigVersionRecord:
        async with self._lock(workspace_id):
            versions = self._versions.get(workspace_id, [])
            if not versions:
                raise RuntimeError("generation config must be initialized before publish")
            current = versions[-1]
            if _comparable_content(current.content) == _comparable_content(content):
                self._drafts[workspace_id] = ConfigDraftRecord(
                    workspace_id, current.version_no, deepcopy(current.content)
                )
                return _copy_version(current)
            draft = self._drafts.get(workspace_id)
            if (
                draft is None
                or draft.base_version_no != expected_base_version_no
                or draft.base_version_no != current.version_no
                or _comparable_content(draft.content)
                != _comparable_content(expected_draft)
            ):
                _draft_conflict()
            if _comparable_content(current.content) == _comparable_content(content):
                self._drafts[workspace_id] = ConfigDraftRecord(
                    workspace_id, current.version_no, deepcopy(current.content)
                )
                return _copy_version(current)
            next_version = current.version_no + 1
            published_content = deepcopy(content)
            published_content["version"] = next_version
            published_content["savedAt"] = saved_at
            published = ConfigVersionRecord(
                id=uuid4(),
                workspace_id=workspace_id,
                version_no=next_version,
                content=published_content,
                content_sha256=generation_config_hash(published_content),
            )
            versions.append(published)
            self._drafts[workspace_id] = ConfigDraftRecord(
                workspace_id, next_version, deepcopy(published_content)
            )
            return _copy_version(published)

    async def ready(self) -> bool:
        return True


class PostgresGenerationConfigRepository:
    """以 PostgreSQL 保存不可变发布版本和工作区草稿。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def bootstrap(
        self, workspace_id: UUID, default_content: dict[str, Any]
    ) -> tuple[ConfigVersionRecord, ConfigDraftRecord]:
        async with self.sessions() as session, session.begin():
            await _lock_workspace(session, workspace_id)
            current = await _current_for_update(session, workspace_id)
            if current is None:
                initial = deepcopy(default_content)
                initial["version"] = 1
                row = await session.execute(
                    text(
                        "INSERT INTO generation_config.config_versions "
                        "(id, workspace_id, version_no, content, content_sha256) "
                        "VALUES (:id, :workspace_id, 1, CAST(:content AS jsonb), :content_sha256) "
                        "RETURNING id, workspace_id, version_no, content, content_sha256, created_at"
                    ),
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "content": json.dumps(initial, ensure_ascii=False),
                        "content_sha256": generation_config_hash(initial),
                    },
                )
                current = _version_from_row(row.mappings().one())
            row = await session.execute(
                text(
                    "INSERT INTO generation_config.config_drafts "
                    "(workspace_id, base_version_no, content) "
                    "VALUES (:workspace_id, :base_version_no, CAST(:content AS jsonb)) "
                    "ON CONFLICT (workspace_id) DO NOTHING "
                    "RETURNING workspace_id, base_version_no, content, updated_at"
                ),
                {
                    "workspace_id": workspace_id,
                    "base_version_no": current.version_no,
                    "content": json.dumps(current.content, ensure_ascii=False),
                },
            )
            created_draft = row.mappings().first()
            if created_draft is not None:
                return current, _draft_from_row(created_draft)
            draft = await _draft_for_update(session, workspace_id)
            if draft is None:
                raise RuntimeError("generation config draft was not created")
            return current, draft

    async def get_current(self, workspace_id: UUID) -> ConfigVersionRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT id, workspace_id, version_no, content, content_sha256, created_at "
                    "FROM generation_config.config_versions "
                    "WHERE workspace_id=:workspace_id ORDER BY version_no DESC LIMIT 1"
                ),
                {"workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _version_from_row(result) if result else None

    async def get_version(
        self, workspace_id: UUID, version_no: int
    ) -> ConfigVersionRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT id, workspace_id, version_no, content, content_sha256, created_at "
                    "FROM generation_config.config_versions "
                    "WHERE workspace_id=:workspace_id AND version_no=:version_no"
                ),
                {"workspace_id": workspace_id, "version_no": version_no},
            )
            result = row.mappings().first()
            return _version_from_row(result) if result else None

    async def list_versions(self, workspace_id: UUID) -> list[ConfigVersionRecord]:
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    "SELECT id, workspace_id, version_no, content, content_sha256, created_at "
                    "FROM generation_config.config_versions "
                    "WHERE workspace_id=:workspace_id ORDER BY version_no"
                ),
                {"workspace_id": workspace_id},
            )
            return [_version_from_row(row) for row in rows.mappings()]

    async def publish(self, workspace_id: UUID, content: dict[str, Any]) -> ConfigVersionRecord:
        content_copy = deepcopy(content)
        async with self.sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:workspace_id))"),
                {"workspace_id": str(workspace_id)},
            )
            next_version = await session.scalar(
                text(
                    "SELECT COALESCE(MAX(version_no), 0) + 1 "
                    "FROM generation_config.config_versions WHERE workspace_id=:workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
            row = await session.execute(
                text(
                    "INSERT INTO generation_config.config_versions "
                    "(id, workspace_id, version_no, content, content_sha256) "
                    "VALUES (:id, :workspace_id, :version_no, CAST(:content AS jsonb), :content_sha256) "
                    "RETURNING id, workspace_id, version_no, content, content_sha256, created_at"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "version_no": int(next_version),
                    "content": json.dumps(content_copy, ensure_ascii=False),
                    "content_sha256": generation_config_hash(content_copy),
                },
            )
            return _version_from_row(row.mappings().one())

    async def get_draft(self, workspace_id: UUID) -> ConfigDraftRecord | None:
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT workspace_id, base_version_no, content, updated_at "
                    "FROM generation_config.config_drafts WHERE workspace_id=:workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
            result = row.mappings().first()
            return _draft_from_row(result) if result else None

    async def replace_draft(
        self, workspace_id: UUID, base_version_no: int, content: dict[str, Any]
    ) -> ConfigDraftRecord:
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "INSERT INTO generation_config.config_drafts "
                    "(workspace_id, base_version_no, content) "
                    "VALUES (:workspace_id, :base_version_no, CAST(:content AS jsonb)) "
                    "ON CONFLICT (workspace_id) DO UPDATE SET "
                    "base_version_no=EXCLUDED.base_version_no, content=EXCLUDED.content, updated_at=now() "
                    "RETURNING workspace_id, base_version_no, content, updated_at"
                ),
                {
                    "workspace_id": workspace_id,
                    "base_version_no": base_version_no,
                    "content": json.dumps(deepcopy(content), ensure_ascii=False),
                },
            )
            return _draft_from_row(row.mappings().one())

    async def replace_draft_if_current(
        self, workspace_id: UUID, base_version_no: int, content: dict[str, Any]
    ) -> ConfigDraftRecord:
        async with self.sessions() as session, session.begin():
            await _lock_workspace(session, workspace_id)
            current = await _current_for_update(session, workspace_id)
            if current is None or current.version_no != base_version_no:
                _draft_conflict()
            return await _upsert_draft(session, workspace_id, base_version_no, content)

    async def discard_draft(self, workspace_id: UUID) -> bool:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "DELETE FROM generation_config.config_drafts "
                    "WHERE workspace_id=:workspace_id RETURNING workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
            return result.first() is not None

    async def reset_draft(self, workspace_id: UUID) -> ConfigDraftRecord:
        async with self.sessions() as session, session.begin():
            await _lock_workspace(session, workspace_id)
            current = await _current_for_update(session, workspace_id)
            if current is None:
                raise RuntimeError("generation config must be initialized before reset")
            return await _upsert_draft(
                session, workspace_id, current.version_no, current.content
            )

    async def publish_draft(
        self,
        workspace_id: UUID,
        expected_base_version_no: int,
        expected_draft: dict[str, Any],
        content: dict[str, Any],
        saved_at: str,
    ) -> ConfigVersionRecord:
        async with self.sessions() as session, session.begin():
            await _lock_workspace(session, workspace_id)
            current = await _current_for_update(session, workspace_id)
            if current is None:
                raise RuntimeError("generation config must be initialized before publish")
            if _comparable_content(current.content) == _comparable_content(content):
                await _upsert_draft(
                    session, workspace_id, current.version_no, current.content
                )
                return current
            draft = await _draft_for_update(session, workspace_id)
            if (
                draft is None
                or draft.base_version_no != expected_base_version_no
                or draft.base_version_no != current.version_no
                or _comparable_content(draft.content)
                != _comparable_content(expected_draft)
            ):
                _draft_conflict()
            if _comparable_content(current.content) == _comparable_content(content):
                await _upsert_draft(
                    session, workspace_id, current.version_no, current.content
                )
                return current
            next_version = current.version_no + 1
            published_content = deepcopy(content)
            published_content["version"] = next_version
            published_content["savedAt"] = saved_at
            row = await session.execute(
                text(
                    "INSERT INTO generation_config.config_versions "
                    "(id, workspace_id, version_no, content, content_sha256) "
                    "VALUES (:id, :workspace_id, :version_no, CAST(:content AS jsonb), :content_sha256) "
                    "RETURNING id, workspace_id, version_no, content, content_sha256, created_at"
                ),
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "version_no": next_version,
                    "content": json.dumps(published_content, ensure_ascii=False),
                    "content_sha256": generation_config_hash(published_content),
                },
            )
            published = _version_from_row(row.mappings().one())
            await _upsert_draft(
                session, workspace_id, published.version_no, published.content
            )
            return published

    async def ready(self) -> bool:
        try:
            async with self.sessions() as session:
                await session.execute(text("SELECT 1 FROM generation_config.config_versions LIMIT 1"))
            return True
        except Exception:
            return False


def _copy_version(record: ConfigVersionRecord) -> ConfigVersionRecord:
    return ConfigVersionRecord(
        record.id,
        record.workspace_id,
        record.version_no,
        deepcopy(record.content),
        record.content_sha256,
        record.created_at,
    )


def _comparable_content(content: dict[str, Any]) -> dict[str, Any]:
    comparable = deepcopy(content)
    comparable.pop("version", None)
    comparable.pop("savedAt", None)
    return comparable


def _draft_conflict() -> None:
    raise AppError(
        "GENERATION_CONFIG_DRAFT_CONFLICT",
        "草稿基线版本已过期，请重新加载当前已发布配置",
        409,
    )


async def _lock_workspace(session: AsyncSession, workspace_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:workspace_id))"),
        {"workspace_id": str(workspace_id)},
    )


async def _current_for_update(
    session: AsyncSession, workspace_id: UUID
) -> ConfigVersionRecord | None:
    row = await session.execute(
        text(
            "SELECT id, workspace_id, version_no, content, content_sha256, created_at "
            "FROM generation_config.config_versions "
            "WHERE workspace_id=:workspace_id ORDER BY version_no DESC LIMIT 1 FOR UPDATE"
        ),
        {"workspace_id": workspace_id},
    )
    result = row.mappings().first()
    return _version_from_row(result) if result else None


async def _draft_for_update(
    session: AsyncSession, workspace_id: UUID
) -> ConfigDraftRecord | None:
    row = await session.execute(
        text(
            "SELECT workspace_id, base_version_no, content, updated_at "
            "FROM generation_config.config_drafts WHERE workspace_id=:workspace_id FOR UPDATE"
        ),
        {"workspace_id": workspace_id},
    )
    result = row.mappings().first()
    return _draft_from_row(result) if result else None


async def _upsert_draft(
    session: AsyncSession,
    workspace_id: UUID,
    base_version_no: int,
    content: dict[str, Any],
) -> ConfigDraftRecord:
    row = await session.execute(
        text(
            "INSERT INTO generation_config.config_drafts "
            "(workspace_id, base_version_no, content) "
            "VALUES (:workspace_id, :base_version_no, CAST(:content AS jsonb)) "
            "ON CONFLICT (workspace_id) DO UPDATE SET "
            "base_version_no=EXCLUDED.base_version_no, content=EXCLUDED.content, updated_at=now() "
            "RETURNING workspace_id, base_version_no, content, updated_at"
        ),
        {
            "workspace_id": workspace_id,
            "base_version_no": base_version_no,
            "content": json.dumps(deepcopy(content), ensure_ascii=False),
        },
    )
    return _draft_from_row(row.mappings().one())


def _copy_draft(record: ConfigDraftRecord) -> ConfigDraftRecord:
    return ConfigDraftRecord(
        record.workspace_id,
        record.base_version_no,
        deepcopy(record.content),
        record.updated_at,
    )


def _version_from_row(row: Any) -> ConfigVersionRecord:
    return ConfigVersionRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        version_no=row["version_no"],
        content=deepcopy(row["content"]),
        content_sha256=row["content_sha256"],
        created_at=row["created_at"],
    )


def _draft_from_row(row: Any) -> ConfigDraftRecord:
    return ConfigDraftRecord(
        workspace_id=row["workspace_id"],
        base_version_no=row["base_version_no"],
        content=deepcopy(row["content"]),
        updated_at=row["updated_at"],
    )
