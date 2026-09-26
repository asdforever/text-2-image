"""图片编辑会话、任务与版本的持久化模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ImageEditSession(Base):
    __tablename__ = "image_edit_sessions"
    __table_args__ = (
        CheckConstraint("revision > 0", name="image_edit_sessions_revision_check"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'queued', 'generating', 'succeeded', 'failed', 'archived')",
            name="image_edit_sessions_status_check",
        ),
        Index("image_edit_sessions_project_status_idx", "project_id", "status", "created_at"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False)
    source_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    operations_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ImageEditOperation(Base):
    __tablename__ = "image_edit_operations"
    __table_args__ = (
        CheckConstraint("revision > 0", name="image_edit_operations_revision_check"),
        CheckConstraint("ordinal > 0", name="image_edit_operations_ordinal_check"),
        UniqueConstraint("session_id", "ordinal", name="uq_image_edit_operations_ordinal"),
        Index("image_edit_operations_session_idx", "session_id", "ordinal"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.image_edit_sessions.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ImageOcrResult(Base):
    __tablename__ = "image_ocr_results"
    __table_args__ = (
        UniqueConstraint("session_id", "source_version_id", "request_fingerprint", name="uq_image_ocr_results_request"),
        Index("image_ocr_results_session_source_idx", "session_id", "source_version_id", "created_at"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.image_edit_sessions.id", ondelete="CASCADE"), nullable=False)
    source_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    regions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    provider_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ImageEditTask(Base):
    __tablename__ = "image_edit_tasks"
    __table_args__ = (
        CheckConstraint("revision > 0", name="image_edit_tasks_revision_check"),
        CheckConstraint(
            "status IN ('queued', 'generating', 'succeeded', 'failed', 'cancelled', 'archived')",
            name="image_edit_tasks_status_check",
        ),
        Index("image_edit_tasks_project_status_idx", "project_id", "status", "created_at"),
        Index(
            "uq_image_edit_tasks_submit_idempotency",
            "session_id",
            "submit_idempotency_key",
            unique=True,
        ),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.image_edit_sessions.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    operations_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prompt_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    final_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    submit_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ImageEditAttempt(Base):
    __tablename__ = "image_edit_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number > 0", name="image_edit_attempts_number_check"),
        CheckConstraint(
            "status IN ('queued', 'generating', 'succeeded', 'failed', 'cancelled')",
            name="image_edit_attempts_status_check",
        ),
        UniqueConstraint("task_id", "attempt_number", name="uq_image_edit_attempts_number"),
        Index("image_edit_attempts_task_idx", "task_id", "created_at"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.image_edit_tasks.id", ondelete="CASCADE"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    provider_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImageEditVersion(Base):
    __tablename__ = "image_edit_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="image_edit_versions_number_check"),
        UniqueConstraint("task_id", "version_number", name="uq_image_edit_versions_number"),
        Index("image_edit_versions_task_idx", "task_id", "created_at"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.image_edit_tasks.id", ondelete="CASCADE"), nullable=False)
    attempt_id: Mapped[UUID | None] = mapped_column(ForeignKey("project_workbench.image_edit_attempts.id", ondelete="SET NULL"), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    preview_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="image/png")
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    prompt_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_final: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
