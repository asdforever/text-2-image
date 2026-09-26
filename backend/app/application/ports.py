from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from ..core.identity import IdentityProvider
from ..repository import ImageRecord, SuiteRecord
from ..storage import StoredObject
from .idempotency import IdempotencyClaim, IdempotencyRecord, MemoryIdempotencyStore


class SuiteRepository(Protocol):
    async def create_suite(self, name: str, workspace_id: UUID, key: str | None = None) -> SuiteRecord: ...
    async def get_suite(self, suite_id: UUID, workspace_id: UUID | None = None) -> SuiteRecord | None: ...
    async def list_suites(self, workspace_id: UUID) -> list[SuiteRecord]: ...
    async def add_image(
        self,
        suite: SuiteRecord,
        image: ImageRecord,
        key: str | None = None,
    ) -> ImageRecord: ...
    async def ready(self) -> bool: ...


class ObjectStoragePort(Protocol):
    async def put(self, obj: StoredObject) -> None: ...
    async def get(self, key: str) -> StoredObject | None: ...
    async def delete(self, key: str) -> None: ...
    async def ready(self) -> bool: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class IdempotencyStore(Protocol):
    async def get(self, scope: str, key: str) -> IdempotencyRecord | None: ...
    async def claim(self, scope: str, key: str, fingerprint: str, *, retry_failed: bool = False) -> IdempotencyClaim: ...
    async def complete(self, scope: str, key: str, fingerprint: str, **kwargs: Any) -> IdempotencyRecord: ...
    async def fail(self, scope: str, key: str, fingerprint: str, **kwargs: Any) -> IdempotencyRecord: ...


IdentityProviderPort = IdentityProvider
