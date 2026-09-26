"""suite_workbench 基线表的结构登记。

这些表由早期迁移建立，业务代码统一通过原生 SQL 访问：

- `suite_workbench.workspaces`：工作区，当前只作为外键目标存在。
- `suite_workbench.suites`、`input_images`：`postgres_repository.py`。
- `suite_workbench.idempotency_keys`：`application/idempotency.py`。
- `suite_workbench.migration_revision_checksums`：`migration_guard.py`。

这里只把它们登记进 `Base.metadata`，不提供 ORM 映射。缺少这份登记时，
多个模型里的 `ForeignKey("suite_workbench.workspaces.id")` 无法解析目标表，
Alembic 的 autogenerate、`alembic check` 和 `Base.metadata.create_all()`
都会抛 `NoReferencedTableError`。
"""

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base

SCHEMA = "suite_workbench"


workspaces = Table(
    "workspaces",
    Base.metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("name", Text(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema=SCHEMA,
)


suites = Table(
    "suites",
    Base.metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column("name", Text(), nullable=False),
    Column("status", Text(), nullable=False, server_default=text("'draft'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "workspace_id",
        Uuid(as_uuid=True),
        ForeignKey(f"{SCHEMA}.workspaces.id"),
        nullable=False,
    ),
    CheckConstraint("status IN ('draft', 'in_progress')", name="suites_status_check"),
    Index("suites_workspace_idx", "workspace_id"),
    schema=SCHEMA,
)


input_images = Table(
    "input_images",
    Base.metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()),
    Column(
        "suite_id",
        Uuid(as_uuid=True),
        ForeignKey(f"{SCHEMA}.suites.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ordinal", Integer(), nullable=False),
    Column("original_object_key", Text(), nullable=False),
    Column("thumbnail_object_key", Text(), nullable=False),
    Column("sha256", CHAR(64), nullable=False),
    Column("width", Integer(), nullable=False),
    Column("height", Integer(), nullable=False),
    Column("mime_type", Text(), nullable=False),
    Column("original_filename", Text(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("suite_id", "ordinal", name="input_images_suite_id_ordinal_key"),
    UniqueConstraint("suite_id", "sha256", name="input_images_suite_id_sha256_key"),
    schema=SCHEMA,
)


idempotency_keys = Table(
    "idempotency_keys",
    Base.metadata,
    Column("scope", Text(), primary_key=True),
    Column("key", Text(), primary_key=True),
    Column("resource_id", Uuid(as_uuid=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "request_fingerprint",
        CHAR(64),
        nullable=False,
        server_default=text("repeat('0', 64)"),
    ),
    Column("status", String(20), nullable=False, server_default=text("'completed'")),
    Column("response_status", Integer(), nullable=True),
    Column("response_body", JSONB(), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "request_fingerprint ~ '^[0-9a-f]{64}$'", name="idempotency_fingerprint_check"
    ),
    CheckConstraint(
        "status IN ('in_progress', 'completed', 'failed')", name="idempotency_status_check"
    ),
    schema=SCHEMA,
)


migration_revision_checksums = Table(
    "migration_revision_checksums",
    Base.metadata,
    Column("revision", String(64), primary_key=True),
    Column("checksum", CHAR(64), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "checksum ~ '^[0-9a-f]{64}$'", name="migration_revision_checksum_format"
    ),
    schema=SCHEMA,
)


__all__ = [
    "SCHEMA",
    "workspaces",
    "suites",
    "input_images",
    "idempotency_keys",
    "migration_revision_checksums",
]
