from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .core.errors import AppError
from .repository import ImageRecord, SuiteRecord
from .migration_guard import EXPECTED_ALEMBIC_HEAD


class PostgresRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        expected_revision: str = EXPECTED_ALEMBIC_HEAD,
    ) -> None:
        self.sessions = sessions
        self.expected_revision = expected_revision

    async def ready(self) -> bool:
        return all((await self.readiness_checks()).values())

    async def readiness_checks(self) -> dict[str, bool]:
        checks = {"database": False, "schema": False, "workspaceScope": False}
        try:
            async with self.sessions() as session:
                await session.execute(text("SELECT 1"))
                checks["database"] = True
                revision = await session.scalar(
                    text("SELECT version_num FROM public.alembic_version")
                )
                checks["schema"] = revision == self.expected_revision
                if checks["schema"]:
                    orphan_count = await session.scalar(
                        text(
                            "SELECT count(*) FROM suite_workbench.suites "
                            "WHERE workspace_id IS NULL"
                        )
                    )
                    checks["workspaceScope"] = orphan_count == 0
        except Exception:
            pass
        return checks

    async def create_suite(self, name: str, workspace_id: UUID, key: str | None = None) -> SuiteRecord:
        async with self.sessions() as session, session.begin():
            if key:
                scope = f"create-suite:{workspace_id}"
                existing = await session.execute(text("SELECT resource_id FROM suite_workbench.idempotency_keys WHERE scope=:scope AND key=:key"), {"scope": scope, "key": key})
                row = existing.first()
                if row:
                    return await self.get_suite(UUID(str(row[0])), workspace_id)  # type: ignore[return-value]
            suite_id = uuid4(); now = datetime.now(timezone.utc)
            await session.execute(text("INSERT INTO suite_workbench.suites (id,workspace_id,name,status,created_at,updated_at) VALUES (:id,:workspace_id,:name,'draft',:created,:updated)"), {"id": suite_id, "workspace_id": workspace_id, "name": name, "created": now, "updated": now})
            if key:
                await session.execute(text("INSERT INTO suite_workbench.idempotency_keys(scope,key,resource_id) VALUES (:scope,:key,:id)"), {"scope": scope, "key": key, "id": suite_id})
            return SuiteRecord(suite_id, name, created_at=now, updated_at=now, workspace_id=workspace_id)

    async def get_suite(self, suite_id: UUID, workspace_id: UUID | None = None) -> SuiteRecord | None:
        async with self.sessions() as session:
            result = await session.execute(text("SELECT id,workspace_id,name,status,created_at,updated_at FROM suite_workbench.suites WHERE id=:id AND (:workspace_id IS NULL OR workspace_id=:workspace_id)"), {"id": suite_id, "workspace_id": workspace_id})
            row = result.mappings().first()
            if not row: return None
            images = await session.execute(text("SELECT id,suite_id,ordinal,original_object_key,thumbnail_object_key,sha256,width,height,mime_type,original_filename,created_at FROM suite_workbench.input_images WHERE suite_id=:id ORDER BY ordinal"), {"id": suite_id})
            records = [ImageRecord(item["id"], item["suite_id"], item["ordinal"], item["original_object_key"], item["thumbnail_object_key"], item["sha256"], item["width"], item["height"], item["mime_type"], item["original_filename"], item["created_at"]) for item in images.mappings()]
            return SuiteRecord(row["id"], row["name"], row["status"], row["created_at"], row["updated_at"], records, row["workspace_id"])

    async def list_suites(self, workspace_id: UUID) -> list[SuiteRecord]:
        async with self.sessions() as session:
            result = await session.execute(text("SELECT id FROM suite_workbench.suites WHERE workspace_id=:workspace_id ORDER BY updated_at DESC"), {"workspace_id": workspace_id})
            suites = []
            for row in result:
                suite = await self.get_suite(row[0], workspace_id)
                if suite: suites.append(suite)
            return suites

    async def add_image(self, suite: SuiteRecord, image: ImageRecord, key: str | None = None) -> ImageRecord:
        async with self.sessions() as session, session.begin():
            if key:
                existing = await session.execute(text("SELECT resource_id FROM suite_workbench.idempotency_keys WHERE scope=:scope AND key=:key"), {"scope": f"upload:{suite.id}", "key": key})
                row = existing.first()
                if row:
                    found = next((item for item in suite.images if item.id == UUID(str(row[0]))), None)
                    if found: return found
            try:
                await session.execute(text("INSERT INTO suite_workbench.input_images (id,suite_id,ordinal,original_object_key,thumbnail_object_key,sha256,width,height,mime_type,original_filename,created_at) VALUES (:id,:suite,:ordinal,:original,:thumbnail,:sha256,:width,:height,:mime,:filename,:created)"), {"id": image.id, "suite": image.suite_id, "ordinal": image.ordinal, "original": image.original_key, "thumbnail": image.thumbnail_key, "sha256": image.sha256, "width": image.width, "height": image.height, "mime": image.mime_type, "filename": image.filename, "created": image.created_at})
            except Exception as exc:
                text_error = str(exc).lower()
                if "ordinal" in text_error: raise AppError("DUPLICATE_ORDINAL", "ordinal already exists", 409) from exc
                if "sha256" in text_error: raise AppError("DUPLICATE_IMAGE", "image already exists", 409) from exc
                raise
            if key:
                await session.execute(text("INSERT INTO suite_workbench.idempotency_keys(scope,key,resource_id) VALUES (:scope,:key,:id)"), {"scope": f"upload:{suite.id}", "key": key, "id": image.id})
            return image
