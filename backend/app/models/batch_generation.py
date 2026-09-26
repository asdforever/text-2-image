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


class GenerationBatch(Base):
    __tablename__ = "generation_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('compiling_prompt', 'awaiting_confirmation', 'queued', 'running', "
            "'succeeded', 'partially_failed', 'failed', 'cancel_requested', 'cancelled')",
            name="generation_batches_status_check",
        ),
        CheckConstraint(
            "kind IN ('hero', 'suite')",
            name="generation_batches_kind_check",
        ),
        UniqueConstraint(
            "workspace_id",
            "compile_idempotency_key",
            name="uq_generation_batches_compile_idempotency",
        ),
        UniqueConstraint(
            "workspace_id",
            "confirm_idempotency_key",
            name="uq_generation_batches_confirm_idempotency",
        ),
        UniqueConstraint(
            "source_plan_id",
            name="uq_generation_batches_source_plan",
        ),
        Index(
            "generation_batches_project_status_idx",
            "project_id",
            "status",
            text("created_at DESC"),
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
    source_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.project_assets.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="hero")
    source_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "project_workbench.suite_plans.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="generation_batches_source_plan_fk",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="compiling_prompt")
    compile_idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    compile_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    confirm_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confirm_fingerprint: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GenerationModuleTask(Base):
    __tablename__ = "generation_module_tasks"
    __table_args__ = (
        CheckConstraint(
            "requested_image_count BETWEEN 1 AND 4",
            name="generation_module_tasks_requested_image_count_check",
        ),
        UniqueConstraint("batch_id", "module_key", name="uq_generation_module_tasks_batch_module"),
        UniqueConstraint("batch_id", "position", name="uq_generation_module_tasks_batch_position"),
        CheckConstraint("position > 0", name="generation_module_tasks_position_check"),
        Index("generation_module_tasks_batch_idx", "batch_id"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.generation_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    module_key: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    compiled_task_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    compiler_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confirmed_task_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_prompt_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GenerationImageSlot(Base):
    __tablename__ = "generation_image_slots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'leased', 'dispatching', 'succeeded', 'failed', "
            "'cancel_requested', 'cancelled', 'needs_retry')",
            name="generation_image_slots_status_check",
        ),
        CheckConstraint("ordinal > 0", name="generation_image_slots_ordinal_check"),
        UniqueConstraint("module_task_id", "ordinal", name="uq_generation_image_slots_module_ordinal"),
        Index("generation_image_slots_batch_idx", "batch_id"),
        Index(
            "generation_image_slots_queue_idx",
            "status",
            "lease_expires_at",
            "created_at",
        ),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.generation_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    module_task_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.generation_module_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    generated_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_workbench.project_assets.id", ondelete="SET NULL"), nullable=True
    )
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GenerationSlotAttempt(Base):
    __tablename__ = "generation_slot_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('leased', 'dispatching', 'succeeded', 'failed', 'cancelled', 'needs_retry')",
            name="generation_slot_attempts_status_check",
        ),
        UniqueConstraint("slot_id", "attempt_no", name="uq_generation_slot_attempts_slot_attempt"),
        Index("generation_slot_attempts_slot_idx", "slot_id", text("attempt_no DESC")),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    slot_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.generation_image_slots.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="leased")
    lease_token: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_request_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
