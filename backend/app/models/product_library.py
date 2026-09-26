"""正式产品库模型；提示词测试产物仍由 prompt_library.asset.Product 管理。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProductLibrary(Base):
    __tablename__ = "product_libraries"
    __table_args__ = (
        CheckConstraint("library_type = 'production'", name="product_libraries_type_check"),
        Index("product_libraries_workspace_active_idx", "workspace_id", "archived_at"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    library_type: Mapped[str] = mapped_column(String(20), nullable=False, default="production")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("product_type IN ('product', 'sku', 'collection')", name="products_type_check"),
        Index("products_library_active_idx", "library_id", "archived_at"),
        Index(
            "uq_products_workspace_project_active",
            "workspace_id",
            "project_id",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL AND archived_at IS NULL"),
        ),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    library_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.product_libraries.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_type: Mapped[str] = mapped_column(String(30), nullable=False, default="product")
    metadata_snapshot: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ProductAssetLink(Base):
    __tablename__ = "product_asset_links"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "project_asset_id",
            name="uq_product_asset_links_product_asset",
        ),
        Index(
            "product_asset_links_project_idx",
            "workspace_id",
            "project_id",
            "created_at",
        ),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.products.id", ondelete="CASCADE"), nullable=False
    )
    project_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.project_assets.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProductVersion(Base):
    __tablename__ = "product_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="product_versions_number_check"),
        CheckConstraint(
            "product_type IN ('hero', 'detail', 'white_background', 'scene', 'edit')",
            name="product_versions_type_check",
        ),
        CheckConstraint(
            "status IN ('published', 'archived')",
            name="product_versions_status_check",
        ),
        UniqueConstraint("product_id", "version_number", name="uq_product_versions_number"),
        Index("product_versions_product_type_idx", "product_id", "product_type", "status", "created_at"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="SET NULL"), nullable=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.products.id", ondelete="CASCADE"), nullable=False)
    source_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_task_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    source_attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    preview_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="image/png")
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prompt_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
