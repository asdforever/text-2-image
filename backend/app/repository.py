from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .core.errors import AppError


@dataclass
class ImageRecord:
    id: UUID
    suite_id: UUID
    ordinal: int
    original_key: str
    thumbnail_key: str
    sha256: str
    width: int
    height: int
    mime_type: str
    filename: str
    created_at: datetime


@dataclass
class SuiteRecord:
    id: UUID
    name: str
    status: str = "draft"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    images: list[ImageRecord] = field(default_factory=list)
    workspace_id: UUID | None = None


class InMemoryRepository:
    def __init__(self) -> None:
        self.suites: dict[UUID, SuiteRecord] = {}
        self.idempotency: dict[tuple[str, str], object] = {}

    async def create_suite(self, name: str, workspace_id: UUID, key: str | None = None) -> SuiteRecord:
        scope = f"create-suite:{workspace_id}"
        if key and (scope, key) in self.idempotency:
            return self.idempotency[(scope, key)]  # type: ignore[return-value]
        now = datetime.now(timezone.utc)
        suite = SuiteRecord(uuid4(), name, created_at=now, updated_at=now, workspace_id=workspace_id)
        self.suites[suite.id] = suite
        if key: self.idempotency[(scope, key)] = suite
        return suite

    async def get_suite(self, suite_id: UUID, workspace_id: UUID | None = None) -> SuiteRecord | None:
        suite = self.suites.get(suite_id)
        if suite is None or (workspace_id is not None and suite.workspace_id != workspace_id):
            return None
        return suite

    async def list_suites(self, workspace_id: UUID) -> list[SuiteRecord]:
        return [suite for suite in self.suites.values() if suite.workspace_id == workspace_id]
    async def ready(self) -> bool: return True

    async def add_image(self, suite: SuiteRecord, image: ImageRecord, key: str | None = None) -> ImageRecord:
        if key and (f"upload:{suite.id}", key) in self.idempotency:
            return self.idempotency[(f"upload:{suite.id}", key)]  # type: ignore[return-value]
        if len(suite.images) >= 6: raise AppError("TOO_MANY_IMAGES", "a suite can contain at most 6 images", 400)
        if any(item.ordinal == image.ordinal for item in suite.images): raise AppError("DUPLICATE_ORDINAL", "ordinal already exists", 409)
        if any(item.sha256 == image.sha256 for item in suite.images): raise AppError("DUPLICATE_IMAGE", "image already exists", 409)
        suite.images.append(image); suite.updated_at = datetime.now(timezone.utc)
        if key: self.idempotency[(f"upload:{suite.id}", key)] = image
        return image
