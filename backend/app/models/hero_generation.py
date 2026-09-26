from datetime import datetime
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class HeroGenerationTask(Base):
    __tablename__ = "hero_generation_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('compiling_prompt', 'awaiting_confirmation', 'generating', 'succeeded', 'failed')",
            name="hero_generation_tasks_status_check",
        ),
        UniqueConstraint(
            "workspace_id",
            "compile_idempotency_key",
            name="uq_hero_generation_compile_idempotency",
        ),
        UniqueConstraint(
            "workspace_id",
            "confirm_idempotency_key",
            name="uq_hero_generation_confirm_idempotency",
        ),
        Index(
            "hero_generation_tasks_project_status_idx",
            "project_id",
            "status",
            text("created_at DESC"),
        ),
        Index("hero_generation_tasks_source_asset_idx", "source_asset_id"),
        {"schema": "project_workbench"},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("suite_workbench.workspaces.id"), nullable=False
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.projects.id", ondelete="CASCADE"), nullable=False
    )
    source_asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_workbench.project_assets.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="compiling_prompt")
    compile_idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    compile_fingerprint: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    confirm_idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confirm_fingerprint: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    compiled_task_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    compiler_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confirmed_task_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_prompt_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    provider_request: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_workbench.project_assets.id", ondelete="SET NULL"), nullable=True
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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
