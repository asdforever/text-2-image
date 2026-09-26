from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SuitePlan(Base):
    __tablename__ = "suite_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('compiling', 'awaiting_confirmation', 'confirmed', 'failed')",
            name="suite_plans_status_check",
        ),
        CheckConstraint("revision > 0", name="suite_plans_revision_check"),
        CheckConstraint(
            "requested_module_count > 0",
            name="suite_plans_module_count_check",
        ),
        UniqueConstraint(
            "workspace_id",
            "compile_idempotency_key",
            name="uq_suite_plans_compile_idempotency",
        ),
        UniqueConstraint(
            "workspace_id",
            "confirm_idempotency_key",
            name="uq_suite_plans_confirm_idempotency",
        ),
        Index("suite_plans_project_latest_idx", "project_id", text("created_at DESC")),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("suite_workbench.workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="compiling")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requested_module_count: Mapped[int] = mapped_column(Integer, nullable=False)
    compile_idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    compile_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    confirm_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confirm_fingerprint: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confirmed_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generation_batch_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_workbench.generation_batches.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SuitePlanModule(Base):
    __tablename__ = "suite_plan_modules"
    __table_args__ = (
        CheckConstraint(
            "position > 0", name="suite_plan_modules_position_check"
        ),
        CheckConstraint(
            "requested_image_count BETWEEN 1 AND 4",
            name="suite_plan_modules_requested_image_count_check",
        ),
        CheckConstraint("revision > 0", name="suite_plan_modules_revision_check"),
        UniqueConstraint("plan_id", "module_key", name="uq_suite_plan_modules_plan_module"),
        UniqueConstraint("plan_id", "position", name="uq_suite_plan_modules_plan_position"),
        Index("suite_plan_modules_plan_idx", "plan_id", "position"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.suite_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    module_key: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    copy_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visual_direction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    module_parameters: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    prompt_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    compiled_task_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    compiler_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    current_task_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
