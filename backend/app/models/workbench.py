from datetime import datetime
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class WorkbenchTask(Base):
    __tablename__ = "workbench_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'queued', 'generating', 'succeeded', 'failed', 'cancelled', 'archived')",
            name="workbench_tasks_status_check",
        ),
        CheckConstraint("prompt_revision > 0", name="workbench_tasks_revision_check"),
        UniqueConstraint("project_id", "plan_snapshot_id", "plan_item_id", name="uq_workbench_tasks_plan_item"),
        Index("workbench_tasks_project_status_idx", "project_id", "status", "ordinal"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False)
    plan_snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("project_workbench.suite_plans.id", ondelete="SET NULL"), nullable=True)
    plan_item_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    image_type: Mapped[str] = mapped_column(String(30), nullable=False, default="detail")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt_draft: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_input_image_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    generation_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    current_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    final_version_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class WorkbenchTaskVersion(Base):
    __tablename__ = "workbench_task_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="workbench_task_versions_number_check"),
        UniqueConstraint("task_id", "version_number", name="uq_workbench_task_versions_number"),
        Index("workbench_task_versions_task_created_idx", "task_id", "created_at"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.workbench_tasks.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("project_workbench.generation_batches.id", ondelete="SET NULL"), nullable=True)
    slot_id: Mapped[UUID | None] = mapped_column(ForeignKey("project_workbench.generation_image_slots.id", ondelete="SET NULL"), nullable=True)
    attempt_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False, default="")
    process_object_keys: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    preview_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, default="image/png")
    prompt_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=False)
    is_final: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkbenchLayout(Base):
    __tablename__ = "workbench_layouts"
    __table_args__ = (
        CheckConstraint("layout_version > 0", name="workbench_layouts_version_check"),
        UniqueConstraint("project_id", name="uq_workbench_layouts_project"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False)
    layout_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    viewport: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    nodes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    groups: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class WorkbenchReference(Base):
    __tablename__ = "workbench_references"
    __table_args__ = (
        CheckConstraint("target_type IN ('plan', 'task')", name="workbench_references_target_type_check"),
        CheckConstraint("resource_type IN ('prompt_template', 'input_image', 'base_image', 'task_image_version', 'process_image', 'reverse_reference_asset')", name="workbench_references_resource_type_check"),
        UniqueConstraint("project_id", "target_type", "target_id", "resource_type", "resource_id", "resource_version", name="uq_workbench_references_resource"),
        Index("workbench_references_target_idx", "project_id", "target_type", "target_id", "archived_at"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    resource_version: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    source_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
