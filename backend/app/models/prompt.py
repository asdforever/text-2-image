from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CHAR, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

SCHEMA = "prompt_library"


class PromptCategory(Base):
    __tablename__ = "prompt_categories"
    __table_args__ = (
        Index("prompt_categories_name_lower_uq", text("lower(name)"), unique=True),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    templates: Mapped[list["PromptTemplate"]] = relationship(back_populates="category")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        Index("prompt_templates_category_idx", "category_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    kind_name: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False, default="plan")
    execution_target: Mapped[str] = mapped_column(String(30), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(ForeignKey("prompt_library.prompt_categories.id", ondelete="SET NULL"), nullable=True)
    default_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "prompt_library.prompt_versions.id",
            use_alter=True,
            name="prompt_templates_default_version_fk",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    versions: Mapped[list["PromptVersion"]] = relationship(back_populates="template", foreign_keys="PromptVersion.template_id")
    category: Mapped[PromptCategory | None] = relationship(back_populates="templates")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version_no", name="prompt_versions_template_id_version_no_key"),
        UniqueConstraint("template_id", "content_sha256", name="prompt_versions_template_id_content_sha256_key"),
        Index("prompt_versions_template_idx", "template_id", text("version_no DESC")),
        {"schema": SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(ForeignKey("prompt_library.prompt_templates.id", ondelete="CASCADE"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    execution_target: Mapped[str] = mapped_column(String(30), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    applicability: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    generation_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="marketplace")
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False, default="local-user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    template: Mapped[PromptTemplate] = relationship(back_populates="versions", foreign_keys=[template_id])
