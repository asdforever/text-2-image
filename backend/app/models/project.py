from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

SCHEMA = "project_workbench"


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="projects_status_check"),
        Index("projects_workspace_status_idx", "workspace_id", "status", text("updated_at DESC")),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("suite_workbench.workspaces.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AssetObject(Base):
    __tablename__ = "asset_objects"
    __table_args__ = (
        CheckConstraint(
            "state IN ('available', 'cleanup_pending', 'cleaned')",
            name="asset_objects_state_check",
        ),
        Index("asset_objects_workspace_sha256_idx", "workspace_id", "sha256"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("suite_workbench.workspaces.id"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    cleanup_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectAsset(Base):
    __tablename__ = "project_assets"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('source', 'white_background', 'generated')",
            name="project_assets_kind_check",
        ),
        CheckConstraint(
            "state IN ('available', 'cleanup_pending', 'deleted')",
            name="project_assets_state_check",
        ),
        Index("project_assets_object_idx", "object_id"),
        Index("project_assets_project_kind_idx", "project_id", "kind", text("created_at DESC")),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False
    )
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.asset_objects.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_workbench.project_assets.id", ondelete="RESTRICT"), nullable=True
    )
    generation_snapshot_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="upload")
    source_library_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_resource_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_resource_version_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectAssetSelection(Base):
    __tablename__ = "project_asset_selections"
    __table_args__ = (
        CheckConstraint(
            "role IN ('source', 'white_background', 'generated')",
            name="project_asset_selections_role_check",
        ),
        {"schema": SCHEMA},
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(30), primary_key=True)
    project_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.project_assets.id", ondelete="RESTRICT"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
