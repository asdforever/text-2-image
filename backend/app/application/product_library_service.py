from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4
import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..core.errors import AppError
from ..core.identity import IdentityProvider


def _now(): return datetime.now(timezone.utc)


@dataclass
class ProductionLibraryRecord:
    id: UUID; workspace_id: UUID; name: str; description: str = ""; archived_at: datetime | None = None; created_at: datetime = field(default_factory=_now)


@dataclass
class ProductionProductRecord:
    id: UUID; library_id: UUID; workspace_id: UUID; name: str; project_id: UUID | None = None; archived_at: datetime | None = None; versions: list[Any] = field(default_factory=list)


@dataclass
class ProductionVersionRecord:
    id: UUID
    product_id: UUID
    product_type: str
    source_snapshot: dict[str, Any]
    preview_url: str = ""
    status: str = "published"
    created_at: datetime = field(default_factory=_now)


@dataclass
class ProductAssetLinkRecord:
    id: UUID
    workspace_id: UUID
    project_id: UUID
    product_id: UUID
    project_asset_id: UUID
    created_at: datetime = field(default_factory=_now)


class ProductLibraryService:
    def __init__(self, identity_provider: IdentityProvider):
        self.identity_provider = identity_provider
        self.libraries: dict[UUID, ProductionLibraryRecord] = {}
        self.products: dict[UUID, ProductionProductRecord] = {}
        self.published: dict[str, ProductionVersionRecord] = {}
        self.asset_links: dict[tuple[UUID, UUID], ProductAssetLinkRecord] = {}

    def _workspace(self): return self.identity_provider.get_context().workspace_id

    async def create_library(self, name: str, description: str = ""):
        if not name.strip(): raise AppError("PRODUCT_LIBRARY_NAME_REQUIRED", "产品库名称不能为空", 400)
        item = ProductionLibraryRecord(uuid4(), self._workspace(), name.strip(), description); self.libraries[item.id] = item; return item

    async def list_libraries(self, include_archived=False):
        return [x for x in self.libraries.values() if x.workspace_id == self._workspace() and (include_archived or x.archived_at is None)]

    async def get_library(self, library_id: UUID):
        item = self.libraries.get(library_id)
        if item is None or item.workspace_id != self._workspace():
            raise AppError("PRODUCT_LIBRARY_NOT_FOUND", "正式产品库不存在", 404)
        return item

    async def archive_library(self, library_id: UUID):
        item = await self.get_library(library_id)
        item.archived_at = _now()
        return item

    async def create_product(self, library_id: UUID, name: str, project_id: UUID | None = None):
        library = self.libraries.get(library_id)
        if library is None or library.workspace_id != self._workspace() or library.archived_at: raise AppError("PRODUCT_LIBRARY_NOT_FOUND", "正式产品库不存在", 404)
        item = ProductionProductRecord(uuid4(), library_id, self._workspace(), name.strip(), project_id); self.products[item.id] = item; return item

    async def list_products(self, library_id: UUID, include_archived=False):
        return [x for x in self.products.values() if x.library_id == library_id and x.workspace_id == self._workspace() and (include_archived or x.archived_at is None)]

    async def archive_product(self, product_id: UUID):
        item = self.products.get(product_id)
        if item is None or item.workspace_id != self._workspace(): raise AppError("PRODUCT_NOT_FOUND", "正式产品不存在", 404)
        item.archived_at = _now(); return item

    async def get_product(self, product_id: UUID):
        item = self.products.get(product_id)
        if item is None or item.workspace_id != self._workspace(): raise AppError("PRODUCT_NOT_FOUND", "正式产品不存在", 404)
        return item

    async def get_project_product(self, project_id: UUID, include_archived: bool = False):
        return next(
            (
                item for item in self.products.values()
                if item.workspace_id == self._workspace()
                and item.project_id == project_id
                and (include_archived or item.archived_at is None)
            ),
            None,
        )

    async def ensure_project_product(self, project_id: UUID, project_name: str):
        product = await self.get_project_product(project_id)
        if product is not None:
            product.name = project_name
            return product
        library = next(
            (
                item for item in self.libraries.values()
                if item.workspace_id == self._workspace()
                and item.name == "项目成品库"
                and item.archived_at is None
            ),
            None,
        )
        if library is None:
            library = await self.create_library("项目成品库", "按项目自动归档的全部资产")
        return await self.create_product(library.id, project_name, project_id=project_id)

    async def link_project_asset(
        self, product_id: UUID, project_id: UUID, project_asset_id: UUID
    ) -> ProductAssetLinkRecord:
        product = await self.get_product(product_id)
        if product.project_id != project_id:
            raise AppError("PROJECT_ASSET_LINK_INVALID", "项目产品或项目资产不存在", 404)
        key = (product_id, project_asset_id)
        existing = self.asset_links.get(key)
        if existing is not None:
            return existing
        link = ProductAssetLinkRecord(
            uuid4(), self._workspace(), project_id, product_id, project_asset_id
        )
        self.asset_links[key] = link
        return link

    async def list_product_asset_links(self, product_id: UUID):
        await self.get_product(product_id)
        return sorted(
            (
                item for item in self.asset_links.values()
                if item.workspace_id == self._workspace() and item.product_id == product_id
            ),
            key=lambda item: (item.created_at, item.id),
        )

    async def unlink_project_asset(
        self, product_id: UUID, project_asset_id: UUID
    ) -> bool:
        await self.get_product(product_id)
        return self.asset_links.pop((product_id, project_asset_id), None) is not None

    async def list_versions(self, product_id: UUID, product_type: str | None = None, status: str | None = None):
        product = await self.get_product(product_id)
        return [v for v in product.versions if (product_type is None or v.product_type == product_type) and (status is None or v.status == status)]

    async def get_version(self, product_id: UUID, version_id: UUID):
        product = await self.get_product(product_id)
        version = next((item for item in product.versions if item.id == version_id), None)
        if version is None:
            raise AppError("PRODUCT_VERSION_NOT_FOUND", "正式产品版本不存在", 404)
        return version

    async def archive_version(self, product_id: UUID, version_id: UUID):
        versions = await self.list_versions(product_id)
        version = next((v for v in versions if v.id == version_id), None)
        if version is None: raise AppError("PRODUCT_VERSION_NOT_FOUND", "正式产品版本不存在", 404)
        version.status = "archived"; return version

    async def publish_version(self, library_id: UUID, product_id: UUID, source_version: dict[str, Any], *, product_type: str, idempotency_key: str | None = None):
        product = self.products.get(product_id)
        if product is None or product.library_id != library_id or product.workspace_id != self._workspace(): raise AppError("PRODUCT_NOT_FOUND", "正式产品不存在", 404)
        if source_version.get("status") not in {"succeeded", "published"}: raise AppError("PRODUCT_SOURCE_NOT_READY", "只能发布已完成的图片版本", 409)
        if idempotency_key and idempotency_key in self.published: return self.published[idempotency_key]
        snapshot = dict(source_version)
        version = ProductionVersionRecord(
            uuid4(),
            product_id,
            product_type,
            snapshot,
            str(snapshot.get("previewUrl") or snapshot.get("preview_url") or ""),
        )
        product.versions.append(version)
        if idempotency_key: self.published[idempotency_key] = version
        return version

    async def archive_project_output(
        self,
        *,
        project_id: UUID,
        project_name: str,
        product_type: str,
        source_version_id: UUID,
        preview_url: str,
        source_snapshot: dict[str, Any],
        prompt_snapshot: dict[str, Any] | None = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> ProductionVersionRecord:
        if product_type not in {"hero", "detail", "white_background", "scene", "edit"}:
            raise AppError("PRODUCT_VERSION_TYPE_INVALID", "正式成品类型无效", 400)
        library = next(
            (
                item for item in self.libraries.values()
                if item.workspace_id == self._workspace()
                and item.archived_at is None
                and item.name == "项目成品库"
            ),
            None,
        )
        if library is None:
            library = await self.create_library("项目成品库", "按项目自动归档的生成成品")
        product = next(
            (
                item for item in self.products.values()
                if item.workspace_id == self._workspace()
                and item.library_id == library.id
                and item.project_id == project_id
                and item.archived_at is None
            ),
            None,
        )
        if product is None:
            product = await self.create_product(library.id, project_name, project_id=project_id)
        existing = next(
            (
                item for item in product.versions
                if item.product_type == product_type
                and item.source_snapshot.get("sourceVersionId") == str(source_version_id)
            ),
            None,
        )
        if existing is not None:
            return existing
        snapshot = {
            **source_snapshot,
            "sourceVersionId": str(source_version_id),
            "promptSnapshot": dict(prompt_snapshot or {}),
            "configSnapshot": dict(config_snapshot or {}),
        }
        version = ProductionVersionRecord(
            uuid4(), product.id, product_type, snapshot, preview_url
        )
        product.versions.append(version)
        return version


class SqlAlchemyProductLibraryService:
    """正式成品库的 PostgreSQL adapter；接口与内存实现保持一致。"""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], identity_provider: IdentityProvider):
        self.sessions = sessions
        self.identity_provider = identity_provider

    def _workspace(self): return self.identity_provider.get_context().workspace_id

    async def _versions(self, product_id: UUID):
        async with self.sessions() as session:
            rows = await session.execute(text("SELECT id, product_id, product_type, source_snapshot, preview_url, status, created_at FROM project_workbench.product_versions WHERE product_id=:product_id ORDER BY version_number"), {"product_id": product_id})
            return [ProductionVersionRecord(row["id"], row["product_id"], row["product_type"], row["source_snapshot"], row["preview_url"], row["status"], row["created_at"]) for row in rows.mappings()]

    async def _product(self, row):
        result = ProductionProductRecord(row["id"], row["library_id"], row["workspace_id"], row["name"], row["project_id"], row["archived_at"])
        result.versions = await self._versions(result.id)
        return result

    async def create_library(self, name: str, description: str = ""):
        if not name.strip(): raise AppError("PRODUCT_LIBRARY_NAME_REQUIRED", "产品库名称不能为空", 400)
        async with self.sessions() as session, session.begin():
            row = await session.execute(text("INSERT INTO project_workbench.product_libraries(id, workspace_id, name, description) VALUES (:id,:workspace,:name,:description) RETURNING id, workspace_id, name, description, archived_at, created_at"), {"id": uuid4(), "workspace": self._workspace(), "name": name.strip(), "description": description})
            value = row.mappings().one(); return ProductionLibraryRecord(value["id"], value["workspace_id"], value["name"], value["description"], value["archived_at"], value["created_at"])

    async def list_libraries(self, include_archived=False):
        clause = "" if include_archived else " AND archived_at IS NULL"
        async with self.sessions() as session:
            rows = await session.execute(text("SELECT id, workspace_id, name, description, archived_at, created_at FROM project_workbench.product_libraries WHERE workspace_id=:workspace" + clause + " ORDER BY created_at"), {"workspace": self._workspace()})
            return [ProductionLibraryRecord(r["id"], r["workspace_id"], r["name"], r["description"], r["archived_at"], r["created_at"]) for r in rows.mappings()]

    async def get_library(self, library_id: UUID):
        async with self.sessions() as session:
            row = await session.execute(text("SELECT id, workspace_id, name, description, archived_at, created_at FROM project_workbench.product_libraries WHERE id=:id AND workspace_id=:workspace"), {"id": library_id, "workspace": self._workspace()})
            value = row.mappings().first()
            if value is None: raise AppError("PRODUCT_LIBRARY_NOT_FOUND", "正式成品库不存在", 404)
            return ProductionLibraryRecord(value["id"], value["workspace_id"], value["name"], value["description"], value["archived_at"], value["created_at"])

    async def list_products(self, library_id: UUID, include_archived=False):
        clause = "" if include_archived else " AND archived_at IS NULL"
        async with self.sessions() as session:
            rows = await session.execute(text("SELECT id, library_id, workspace_id, name, project_id, archived_at FROM project_workbench.products WHERE library_id=:library AND workspace_id=:workspace" + clause + " ORDER BY created_at"), {"library": library_id, "workspace": self._workspace()})
            return [await self._product(row) for row in rows.mappings()]

    async def create_product(self, library_id: UUID, name: str, project_id: UUID | None = None):
        await self.get_library(library_id)
        async with self.sessions() as session, session.begin():
            row = await session.execute(text("INSERT INTO project_workbench.products(id, library_id, workspace_id, project_id, name) VALUES (:id,:library,:workspace,:project,:name) RETURNING id, library_id, workspace_id, name, project_id, archived_at"), {"id": uuid4(), "library": library_id, "workspace": self._workspace(), "project": project_id, "name": name.strip()})
            return await self._product(row.mappings().one())

    async def get_product(self, product_id: UUID):
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT id, library_id, workspace_id, name, project_id, archived_at "
                    "FROM project_workbench.products "
                    "WHERE id=:id AND workspace_id=:workspace"
                ),
                {"id": product_id, "workspace": self._workspace()},
            )
            value = row.mappings().first()
            if value is None:
                raise AppError("PRODUCT_NOT_FOUND", "正式产品不存在", 404)
            return await self._product(value)

    async def get_project_product(self, project_id: UUID, include_archived: bool = False):
        archived_clause = "" if include_archived else " AND archived_at IS NULL"
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT id, library_id, workspace_id, name, project_id, archived_at "
                    "FROM project_workbench.products WHERE workspace_id=:workspace "
                    "AND project_id=:project"
                    + archived_clause
                    + " ORDER BY archived_at NULLS FIRST, created_at LIMIT 1"
                ),
                {"workspace": self._workspace(), "project": project_id},
            )
            value = row.mappings().first()
            return await self._product(value) if value is not None else None

    async def ensure_project_product(self, project_id: UUID, project_name: str):
        workspace = self._workspace()
        async with self.sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"project-archive:{workspace}"},
            )
            library_id = await session.scalar(
                text(
                    "SELECT id FROM project_workbench.product_libraries "
                    "WHERE workspace_id=:workspace AND name='项目成品库' "
                    "AND archived_at IS NULL ORDER BY created_at LIMIT 1"
                ),
                {"workspace": workspace},
            )
            if library_id is None:
                library_id = uuid4()
                await session.execute(
                    text(
                        "INSERT INTO project_workbench.product_libraries("
                        "id, workspace_id, name, description) VALUES ("
                        ":id, :workspace, '项目成品库', '按项目自动归档的全部资产')"
                    ),
                    {"id": library_id, "workspace": workspace},
                )
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.products("
                    "id, workspace_id, library_id, project_id, name) VALUES ("
                    ":id, :workspace, :library, :project, :name) "
                    "ON CONFLICT (workspace_id, project_id) "
                    "WHERE project_id IS NOT NULL AND archived_at IS NULL "
                    "DO UPDATE SET name=EXCLUDED.name, updated_at=now() "
                    "RETURNING id, library_id, workspace_id, name, project_id, archived_at"
                ),
                {
                    "id": uuid4(),
                    "workspace": workspace,
                    "library": library_id,
                    "project": project_id,
                    "name": project_name,
                },
            )
            return await self._product(row.mappings().one())

    async def list_versions(
        self,
        product_id: UUID,
        product_type: str | None = None,
        status: str | None = None,
    ):
        await self.get_product(product_id)
        clauses = ["product_id=:product"]
        params: dict[str, Any] = {"product": product_id}
        if product_type is not None:
            clauses.append("product_type=:product_type")
            params["product_type"] = product_type
        if status is not None:
            clauses.append("status=:status")
            params["status"] = status
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    "SELECT id, product_id, product_type, source_snapshot, preview_url, "
                    "status, created_at FROM project_workbench.product_versions WHERE "
                    + " AND ".join(clauses)
                    + " ORDER BY version_number"
                ),
                params,
            )
            return [
                ProductionVersionRecord(
                    row["id"],
                    row["product_id"],
                    row["product_type"],
                    row["source_snapshot"],
                    row["preview_url"],
                    row["status"],
                    row["created_at"],
                )
                for row in rows.mappings()
            ]

    async def get_version(self, product_id: UUID, version_id: UUID):
        await self.get_product(product_id)
        async with self.sessions() as session:
            row = await session.execute(
                text(
                    "SELECT id, product_id, product_type, source_snapshot, preview_url, "
                    "status, created_at FROM project_workbench.product_versions "
                    "WHERE id=:id AND product_id=:product"
                ),
                {"id": version_id, "product": product_id},
            )
            value = row.mappings().first()
            if value is None:
                raise AppError("PRODUCT_VERSION_NOT_FOUND", "正式产品版本不存在", 404)
            return ProductionVersionRecord(
                value["id"],
                value["product_id"],
                value["product_type"],
                value["source_snapshot"],
                value["preview_url"],
                value["status"],
                value["created_at"],
            )

    async def publish_version(
        self,
        library_id: UUID,
        product_id: UUID,
        source_version: dict[str, Any],
        *,
        product_type: str,
        idempotency_key: str | None = None,
    ):
        if product_type not in {"hero", "detail", "white_background", "scene", "edit"}:
            raise AppError("PRODUCT_VERSION_TYPE_INVALID", "正式成品类型无效", 400)
        if source_version.get("status") not in {"succeeded", "published"}:
            raise AppError("PRODUCT_SOURCE_NOT_READY", "只能发布已完成的图片版本", 409)
        try:
            source_version_id = UUID(str(source_version["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError("PRODUCT_SOURCE_ID_INVALID", "来源版本标识无效", 400) from exc

        product = await self.get_product(product_id)
        if product.library_id != library_id:
            raise AppError("PRODUCT_NOT_FOUND", "正式产品不存在", 404)
        workspace = self._workspace()
        async with self.sessions() as session, session.begin():
            if idempotency_key:
                existing = await session.execute(
                    text(
                        "SELECT id, product_id, product_type, source_snapshot, preview_url, "
                        "status, created_at FROM project_workbench.product_versions "
                        "WHERE workspace_id=:workspace AND idempotency_key=:key"
                    ),
                    {"workspace": workspace, "key": idempotency_key},
                )
                value = existing.mappings().first()
                if value is not None:
                    return ProductionVersionRecord(
                        value["id"], value["product_id"], value["product_type"],
                        value["source_snapshot"], value["preview_url"],
                        value["status"], value["created_at"],
                    )
            version_number = int(
                await session.scalar(
                    text(
                        "SELECT COALESCE(MAX(version_number), 0) + 1 "
                        "FROM project_workbench.product_versions WHERE product_id=:product"
                    ),
                    {"product": product_id},
                )
            )
            snapshot = dict(source_version)
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.product_versions("
                    "id, workspace_id, project_id, product_id, source_version_id, "
                    "version_number, product_type, object_key, preview_url, source_snapshot, "
                    "prompt_snapshot, config_snapshot, idempotency_key) VALUES ("
                    ":id, :workspace, :project, :product, :source, :number, :type, :object_key, "
                    ":preview, CAST(:snapshot AS jsonb), '{}'::jsonb, '{}'::jsonb, :key) "
                    "RETURNING id, product_id, product_type, source_snapshot, preview_url, "
                    "status, created_at"
                ),
                {
                    "id": uuid4(),
                    "workspace": workspace,
                    "project": product.project_id,
                    "product": product_id,
                    "source": source_version_id,
                    "number": version_number,
                    "type": product_type,
                    "object_key": str(snapshot.get("objectKey") or ""),
                    "preview": str(snapshot.get("previewUrl") or snapshot.get("preview_url") or ""),
                    "snapshot": json.dumps(snapshot),
                    "key": idempotency_key,
                },
            )
            value = row.mappings().one()
            return ProductionVersionRecord(
                value["id"], value["product_id"], value["product_type"],
                value["source_snapshot"], value["preview_url"],
                value["status"], value["created_at"],
            )

    async def archive_version(self, product_id: UUID, version_id: UUID):
        await self.get_product(product_id)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.product_versions SET status='archived', "
                    "archived_at=COALESCE(archived_at, now()) "
                    "WHERE id=:id AND product_id=:product "
                    "RETURNING id, product_id, product_type, source_snapshot, preview_url, "
                    "status, created_at"
                ),
                {"id": version_id, "product": product_id},
            )
            value = row.mappings().first()
            if value is None:
                raise AppError("PRODUCT_VERSION_NOT_FOUND", "正式产品版本不存在", 404)
            return ProductionVersionRecord(
                value["id"], value["product_id"], value["product_type"],
                value["source_snapshot"], value["preview_url"],
                value["status"], value["created_at"],
            )

    async def archive_product(self, product_id: UUID):
        await self.get_product(product_id)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.products SET archived_at=COALESCE(archived_at, now()), "
                    "updated_at=now() WHERE id=:id AND workspace_id=:workspace "
                    "RETURNING id, library_id, workspace_id, name, project_id, archived_at"
                ),
                {"id": product_id, "workspace": self._workspace()},
            )
            return await self._product(row.mappings().one())

    async def archive_library(self, library_id: UUID):
        await self.get_library(library_id)
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                text(
                    "UPDATE project_workbench.product_libraries "
                    "SET archived_at=COALESCE(archived_at, now()), updated_at=now() "
                    "WHERE id=:id AND workspace_id=:workspace "
                    "RETURNING id, workspace_id, name, description, archived_at, created_at"
                ),
                {"id": library_id, "workspace": self._workspace()},
            )
            value = row.mappings().one()
            return ProductionLibraryRecord(
                value["id"], value["workspace_id"], value["name"], value["description"],
                value["archived_at"], value["created_at"],
            )

    async def link_project_asset(
        self,
        product_id: UUID,
        project_id: UUID,
        project_asset_id: UUID,
    ) -> ProductAssetLinkRecord:
        workspace = self._workspace()
        async with self.sessions() as session, session.begin():
            valid = await session.scalar(
                text(
                    "SELECT p.id FROM project_workbench.products AS p "
                    "JOIN project_workbench.project_assets AS asset "
                    "  ON asset.id=:asset AND asset.project_id=:project "
                    "JOIN project_workbench.projects AS project "
                    "  ON project.id=asset.project_id AND project.workspace_id=:workspace "
                    "WHERE p.id=:product AND p.workspace_id=:workspace "
                    "AND p.project_id=:project "
                    "AND asset.state='available'"
                ),
                {
                    "asset": project_asset_id,
                    "project": project_id,
                    "product": product_id,
                    "workspace": workspace,
                },
            )
            if valid is None:
                raise AppError(
                    "PROJECT_ASSET_LINK_INVALID",
                    "项目产品或项目资产不存在",
                    404,
                )
            row = await session.execute(
                text(
                    "INSERT INTO project_workbench.product_asset_links("
                    "id, workspace_id, project_id, product_id, project_asset_id) "
                    "VALUES (:id, :workspace, :project, :product, :asset) "
                    "ON CONFLICT ON CONSTRAINT uq_product_asset_links_product_asset "
                    "DO UPDATE SET project_asset_id=EXCLUDED.project_asset_id "
                    "RETURNING id, workspace_id, project_id, product_id, "
                    "project_asset_id, created_at"
                ),
                {
                    "id": uuid4(),
                    "workspace": workspace,
                    "project": project_id,
                    "product": product_id,
                    "asset": project_asset_id,
                },
            )
            value = row.mappings().one()
            return ProductAssetLinkRecord(**value)

    async def list_product_asset_links(
        self, product_id: UUID
    ) -> list[ProductAssetLinkRecord]:
        await self.get_product(product_id)
        async with self.sessions() as session:
            rows = await session.execute(
                text(
                    "SELECT id, workspace_id, project_id, product_id, project_asset_id, "
                    "created_at FROM project_workbench.product_asset_links "
                    "WHERE product_id=:product AND workspace_id=:workspace ORDER BY created_at, id"
                ),
                {"product": product_id, "workspace": self._workspace()},
            )
            return [ProductAssetLinkRecord(**row) for row in rows.mappings()]

    async def unlink_project_asset(
        self, product_id: UUID, project_asset_id: UUID
    ) -> bool:
        await self.get_product(product_id)
        async with self.sessions() as session, session.begin():
            removed = await session.scalar(
                text(
                    "DELETE FROM project_workbench.product_asset_links "
                    "WHERE product_id=:product AND project_asset_id=:asset "
                    "AND workspace_id=:workspace RETURNING id"
                ),
                {
                    "product": product_id,
                    "asset": project_asset_id,
                    "workspace": self._workspace(),
                },
            )
            return removed is not None

    async def archive_project_output(self, *, project_id: UUID, project_name: str, product_type: str, source_version_id: UUID, preview_url: str, source_snapshot: dict[str, Any], prompt_snapshot: dict[str, Any] | None = None, config_snapshot: dict[str, Any] | None = None):
        async with self.sessions() as session, session.begin():
            workspace = self._workspace()
            library = (await session.execute(text("SELECT id FROM project_workbench.product_libraries WHERE workspace_id=:workspace AND name='项目成品库' AND archived_at IS NULL LIMIT 1"), {"workspace": workspace})).scalar()
            if library is None:
                library = uuid4(); await session.execute(text("INSERT INTO project_workbench.product_libraries(id, workspace_id, name, description) VALUES (:id,:workspace,'项目成品库','按项目自动归档的生成成品')"), {"id": library, "workspace": workspace})
            product = (await session.execute(text("SELECT id FROM project_workbench.products WHERE workspace_id=:workspace AND library_id=:library AND project_id=:project AND archived_at IS NULL LIMIT 1"), {"workspace": workspace, "library": library, "project": project_id})).scalar()
            if product is None:
                product = uuid4(); await session.execute(text("INSERT INTO project_workbench.products(id, workspace_id, library_id, project_id, name) VALUES (:id,:workspace,:library,:project,:name)"), {"id": product, "workspace": workspace, "library": library, "project": project_id, "name": project_name})
            existing = await session.execute(text("SELECT id, product_id, product_type, source_snapshot, preview_url, status, created_at FROM project_workbench.product_versions WHERE product_id=:product AND product_type=:type AND source_version_id=:source LIMIT 1"), {"product": product, "type": product_type, "source": source_version_id})
            row = existing.mappings().first()
            if row is not None: return ProductionVersionRecord(row["id"], row["product_id"], row["product_type"], row["source_snapshot"], row["preview_url"], row["status"], row["created_at"])
            number = int((await session.scalar(text("SELECT count(*) FROM project_workbench.product_versions WHERE product_id=:product"), {"product": product})) or 0) + 1
            version_id = uuid4(); snapshot = {**source_snapshot, "sourceVersionId": str(source_version_id), "promptSnapshot": prompt_snapshot or {}, "configSnapshot": config_snapshot or {}}
            row = await session.execute(text("INSERT INTO project_workbench.product_versions(id,workspace_id,project_id,product_id,source_version_id,version_number,product_type,object_key,preview_url,source_snapshot,prompt_snapshot,config_snapshot) VALUES (:id,:workspace,:project,:product,:source,:number,:type,'',:preview,CAST(:snapshot AS jsonb),CAST(:prompt AS jsonb),CAST(:config AS jsonb)) RETURNING id, product_id, product_type, source_snapshot, preview_url, status, created_at"), {"id": version_id, "workspace": workspace, "project": project_id, "product": product, "source": source_version_id, "number": number, "type": product_type, "preview": preview_url, "snapshot": json.dumps(snapshot), "prompt": json.dumps(prompt_snapshot or {}), "config": json.dumps(config_snapshot or {})})
            row = row.mappings().one(); return ProductionVersionRecord(row["id"], row["product_id"], row["product_type"], row["source_snapshot"], row["preview_url"], row["status"], row["created_at"])
