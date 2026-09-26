from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Integer, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

SCHEMA = "generation_config"


class ConfigVersion(Base):
    __tablename__ = "config_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version_no", name="uq_config_versions_workspace_version"),
        Index("config_versions_content_sha256_idx", "content_sha256"),
        Index("config_versions_workspace_version_idx", "workspace_id", text("version_no DESC")),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("suite_workbench.workspaces.id"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConfigDraft(Base):
    __tablename__ = "config_drafts"
    __table_args__ = {"schema": SCHEMA}

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("suite_workbench.workspaces.id"), primary_key=True
    )
    base_version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
