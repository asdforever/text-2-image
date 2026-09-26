from datetime import datetime
from uuid import UUID, uuid4
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, JSON, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    pass

SCHEMA = "prompt_library"


class AssetLibrary(Base):
    __tablename__ = "asset_libraries"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'image' or 'text'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    assets: Mapped[list["Asset"]] = relationship(back_populates="library", cascade="all, delete-orphan")


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("assets_library_idx", "library_id"),
        Index("assets_type_idx", "asset_type"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    library_id: Mapped[UUID] = mapped_column(ForeignKey("prompt_library.asset_libraries.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'image' or 'text'

    # 图片素材字段
    minio_bucket: Mapped[str | None] = mapped_column(String(100), nullable=True)
    minio_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 文本素材字段
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, server_default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    library: Mapped[AssetLibrary] = relationship(back_populates="assets")


class TestProductLibrary(Base):
    __tablename__ = "product_libraries"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    library_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'test' or 'project'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    products: Mapped[list["TestProduct"]] = relationship(
        back_populates="library",
        cascade="all, delete-orphan",
    )


class TestProduct(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("products_library_idx", "library_id"),
        Index(
            "uq_prompt_products_test_run",
            "test_run_id",
            unique=True,
            postgresql_where=text("test_run_id IS NOT NULL"),
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    library_id: Mapped[UUID] = mapped_column(ForeignKey("prompt_library.product_libraries.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    product_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'image', 'video', 'text', etc.

    minio_bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    minio_key: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    test_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("prompt_library.test_runs.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, server_default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    library: Mapped[TestProductLibrary] = relationship(
        back_populates="products",
        foreign_keys=[library_id],
    )
    test_run: Mapped["TestRun | None"] = relationship(
        back_populates="output_product",
        foreign_keys=[test_run_id],
    )


class TestRun(Base):
    __tablename__ = "test_runs"
    __table_args__ = (
        Index("test_runs_version_idx", "prompt_version_id"),
        Index("test_runs_asset_idx", "input_asset_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    prompt_version_id: Mapped[UUID] = mapped_column(ForeignKey("prompt_library.prompt_versions.id", ondelete="CASCADE"), nullable=False)

    # 输入
    input_asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("prompt_library.assets.id", ondelete="SET NULL"), nullable=True)
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # 输出
    output_product_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)  # 外键在 Product 表中定义
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 执行信息
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    input_asset: Mapped[Asset | None] = relationship(foreign_keys=[input_asset_id])
    output_product: Mapped[TestProduct | None] = relationship(
        back_populates="test_run",
    )
